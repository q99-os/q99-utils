from typing import Any

from q99_utils.integrations.mappers.openwells_base import OpenWellsAgentMapper
from q99_utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DRILLING_PHASES: tuple[str, ...] = ("GUIA", "INT1", "INT2", "PROD")


class OpenWellsEDMMapper(OpenWellsAgentMapper):
    """OpenWells agent mapper for the EDM schema.

    Canonical SQL is written in MSSQL T-SQL. For non-tsql dialects the
    ``_compile`` seam transpiles at execute time, which needs the ``openwells``
    extra (``pip install q99-utils[openwells]``). The
    drilling-phase enum is customer-specific (not schema-specific) and is
    parameterized via ``drilling_phases``.
    """

    def __init__(
        self,
        driver: Any,
        *,
        dialect: str = "tsql",
        drilling_phases: tuple[str, ...] = DEFAULT_DRILLING_PHASES,
    ):
        self._driver = driver
        self._dialect = dialect
        self._drilling_phases = drilling_phases

    def _compile(self, sql: str) -> str:
        if self._dialect == "tsql":
            return sql
        import sqlglot
        return sqlglot.transpile(sql, read="tsql", write=self._dialect)[0]

    def _phase_placeholders(self) -> str:
        return ", ".join(["?"] * len(self._drilling_phases))

    async def fetch_general(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                well_id, well_legal_name, well_common_name,
                well_uwi, well_uwi_type, api_no, site_id, completion_well_id,
                field_name, field_number, well_operator, well_operator_original, target_formation,
                loc_country, loc_state, loc_county,
                geo_latitude, geo_longitude, datum_name,
                is_offshore, is_platform, is_subsea, is_multilateral, is_lake_drilled,
                lake_height, well_geometry, wellhead_depth, water_depth,
                spud_date, conductor_install_date, regulatory_spud_date, regulatory_install_date,
                redrill_no, redrill_prev_well_id, previous_well_name,
                is_h2s_present, is_co2_present, is_lsa_present,
                maasp_a, maasp_b, maasp_c, maasp_d,
                lease_type, well_net_int, well_working_int,
                lahee_class, well_purpose,
                remarks, reason, well_desc, well_desc_alternate, well_directions, road_description
            FROM CD_WELL_SOURCE
            WHERE well_id = ?
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_activities(self, well_id: str) -> list[dict]:
        sql = f"""
            SELECT
                activity_id,
                time_from,
                time_to,
                activity_duration,
                activity_phase,
                step_no,
                activity_class,
                activity_code,
                activity_subcode,
                npt_level,
                failure_id,
                daily_id,
                CAST(activity_memo AS NVARCHAR(MAX)) as activity_memo,
                md_from,
                md_to,
                off_bottom_torque,
                on_bottom_torque,
                pickup_weight,
                slackoff_weight,
                CAST(service_company AS NVARCHAR(MAX)) as service_company
            FROM DM_ACTIVITY
            WHERE
                well_id = ?
                AND activity_phase IN ({self._phase_placeholders()})
            ORDER BY time_from
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id, *self._drilling_phases))

    async def fetch_sections(self, well_id: str) -> list[dict]:
        sql = f"""
            SELECT
                activity_phase AS phase,
                MIN(time_from) AS date_init,
                MAX(time_to) AS date_end,
                MIN(md_from) AS md_from,
                MAX(md_to) AS md_to,
                ROUND(SUM(activity_duration), 2) AS total_hours
            FROM DM_ACTIVITY
            WHERE
                well_id = ?
                AND activity_phase IN ({self._phase_placeholders()})
            GROUP BY activity_phase
            ORDER BY MIN(time_from)
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id, *self._drilling_phases))

    async def fetch_surveys(self, well_id: str) -> list[dict]:
        sql = """
            WITH latest_survey AS (
                SELECT TOP 1
                    def_survey_header_id,
                    well_id
                FROM CD_DEFINITIVE_SURVEY_HEADER
                WHERE
                    well_id = ?
                    AND phase = 'ACTUAL'
                ORDER BY update_date DESC
            )
            SELECT
                dss.md,
                dss.inclination,
                dss.azimuth,
                dss.tvd,
                dss.dogleg_severity
            FROM CD_DEFINITIVE_SURVEY_STATION dss
            INNER JOIN latest_survey ls
                ON ls.def_survey_header_id = dss.def_survey_header_id
            ORDER BY dss.sequence_no ASC
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_casing(self, well_id: str) -> list[dict]:
        sql = """
            SELECT DISTINCT
                dpr.date_report,
                dpd.nominal_size,
                dpr.run_length,
                ca.hole_size
            FROM DM_PIPE_RUN AS dpr
            RIGHT JOIN DM_PIPE_DATA AS dpd
                ON dpr.assembly_id = dpd.assembly_id
            LEFT JOIN CD_ASSEMBLY AS ca
                ON ca.assembly_id = dpr.assembly_id
            WHERE dpr.well_id = ?
                AND dpd.comp_name = 'Casing'
                AND dpr.run_tally_type = 'RUN'
                AND ca.string_type = 'Casing'
            ORDER BY dpr.date_report
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_bha(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                ca.assembly_name,
                ROUND(cbcb.bit_size, 2) AS bit_size,
                cbcb.iadc_code,
                cbcb.bit_no,
                cbcb.rerun_no,
                cbcb.hours_on_bit,
                dbr.md_in,
                dbr.md_out,
                dbr.purpose,
                dbr.date_in,
                dbr.date_out,
                ca.length_total AS bha_length,
                CONCAT(cbcb.iadc_inner,'-',cbcb.iadc_outer,'-',cbcb.iadc_dull,'-',cbcb.iadc_location,'-',cbcb.iadc_bearing,'-',cbcb.iadc_gauge,'-',cbcb.iadc_other,'-',cbcb.iadc_reason_pulled) AS dull_grading,
                ROUND(
                    (dbr.md_out - dbr.md_in) / NULLIF(
                        CAST(DATEDIFF(SECOND, dbr.date_in, dbr.date_out) AS FLOAT) / 3600.0
                        - ISNULL((
                            SELECT SUM(da.activity_duration)
                            FROM DM_ACTIVITY da
                            WHERE da.well_id = dbr.well_id
                              AND da.activity_class IN ('NP', 'NE')
                              AND da.time_from >= dbr.date_in
                              AND da.time_to <= dbr.date_out
                        ), 0),
                    0),
                2) AS avg_rop_per_hour,
                ISNULL((
                    SELECT SUM(da2.activity_duration)
                    FROM DM_ACTIVITY da2
                    WHERE da2.well_id = dbr.well_id
                      AND da2.activity_class IN ('NP', 'NE')
                      AND da2.time_from >= dbr.date_in
                      AND da2.time_to <= dbr.date_out
                ), 0) AS npt_hours_in_run,
                dbr.daily_sliding_footage,
                dbr.daily_rotating_footage,
                dbr.daily_sliding_hours,
                dbr.daily_rotating_hours
            FROM DM_BHA_RUN AS dbr
            LEFT JOIN CD_BHA_COMP_BIT AS cbcb
                ON cbcb.assembly_id = dbr.assembly_id
            LEFT JOIN CD_ASSEMBLY AS ca
                ON ca.assembly_id = dbr.assembly_id
            WHERE dbr.well_id = ?
            ORDER BY dbr.date_in
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_bha_components(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                ca.assembly_name,
                cac.comp_name,
                cac.comp_type_code,
                cac.sect_type_code,
                cac.catalog_key_desc,
                cac.description,
                ROUND(cac.od_body, 3) AS od_body,
                ROUND(cac.id_body, 3) AS id_body,
                ROUND(cac.length, 3) AS length,
                ROUND(cac.md_top, 2) AS md_top,
                ROUND(cac.md_base, 2) AS md_base,
                cac.tfa,
                cac.max_bend,
                cac.blade_length,
                cac.joints,
                cac.sequence_no
            FROM CD_ASSEMBLY_COMP cac
            JOIN CD_ASSEMBLY ca ON ca.assembly_id = cac.assembly_id
            WHERE ca.well_id = ?
            ORDER BY ca.assembly_name, cac.sequence_no
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_fluids(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                fluid_name,
                type_mud_system,
                mud_supplier,
                density,
                plastic_viscosity,
                yield_point,
                gels_10_sec,
                gels_10_min,
                gels_30_min,
                ph,
                percent_water,
                percent_oil,
                api_water_loss,
                filter_cake,
                mbt,
                conc_cl,
                conc_ca,
                viscosity_funnel,
                md_mud_sample,
                check_date
            FROM CD_FLUID
            WHERE well_id = ?
            ORDER BY md_mud_sample ASC, create_date ASC
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_cement(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                job_desc,
                job_type,
                contractor,
                contractor_foreman,
                job_start_date,
                job_end_date,
                woc,
                toc_md,
                toc_tvd,
                toc_locate_method,
                cbl_quality,
                cet_quality,
                shoe_test_press,
                casing_test_press,
                casing_test_duration,
                bottom_hole_temperature,
                geothermal_gradient,
                surface_ground_temp,
                md_float,
                tvd_float,
                rat_hole_length,
                is_zone_isolated,
                is_toc_sufficient,
                num_squeezes,
                pipe_movement_desc,
                CAST(cement_job_note AS NVARCHAR(MAX)) as cement_job_note,
                assembly_id,
                event_id
            FROM CD_CEMENT_JOB
            WHERE well_id = ?
            ORDER BY job_start_date ASC
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_npt_events(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                ef.failure_title,
                CAST(ef.failure_description AS NVARCHAR(MAX)) AS failure_description,
                ef.date_failure_start,
                ef.date_failure_end,
                ef.failure_duration,
                ef.failure_depth,
                ef.npt_cause_code,
                ef.npt_desc_code,
                ef.npt_operation_type,
                ef.npt_net_time,
                ef.npt_nested_time,
                ef.npt_level,
                ef.equip_fail_type,
                ef.contractor_name,
                ef.npt_total_cost_net,
                ef.failure_total_cost,
                ef.event_id,
                ef.first_activity_id,
                ef.last_activity_id,
                a.activity_phase AS phase
            FROM DM_OPER_EQUIP_FAIL ef
            LEFT JOIN DM_ACTIVITY a
                ON a.well_id = ef.well_id
                AND a.activity_id = ef.first_activity_id
            WHERE ef.well_id = ?
            ORDER BY ef.date_failure_start
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_mud_products(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                product_name,
                unit_price,
                unit_size,
                unit_measure,
                date_first_used,
                mud_function,
                event_id,
                sequence_no
            FROM DM_MUD_PRODUCT
            WHERE well_id = ?
            ORDER BY date_first_used, sequence_no
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_solids_control(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                'hydroclone' AS equipment_type,
                date_op,
                ROUND(md_op, 2) AS md_op,
                duration,
                density_feed,
                density_overflow,
                density_underflow,
                flowrate_feed,
                flowrate_overflow,
                flowrate_underflow,
                press_op,
                NULL AS rpm
            FROM DM_HYDROCLONE_OP
            WHERE well_id = ?
            UNION ALL
            SELECT
                'centrifuge',
                date_op,
                ROUND(md_op, 2),
                duration,
                density_feed,
                density_overflow,
                density_underflow,
                feed_flowrate,
                overflow_flowrate,
                underflow_flowrate,
                NULL,
                rpm
            FROM DM_CENTRIFUGE_OP
            WHERE well_id = ?
            ORDER BY date_op
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id, well_id))

    async def fetch_plan(self, well_id: str) -> list[dict]:
        sql = f"""
            SELECT
                md_from,
                md_to,
                activity_memo,
                sequence_no,
                activity_phase,
                target_duration
            FROM DM_WELL_PLAN_OP
            WHERE
                well_id = ?
                AND activity_phase IN ({self._phase_placeholders()})
            ORDER BY activity_phase, sequence_no
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id, *self._drilling_phases))

    async def fetch_phase_summary(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                activity_phase,
                COUNT(*) AS activity_count,
                MIN(time_from) AS earliest_start,
                MAX(time_to) AS latest_end,
                ROUND(SUM(activity_duration), 2) AS total_hours,
                ROUND(MIN(md_from), 2) AS min_depth,
                ROUND(MAX(md_to), 2) AS max_depth
            FROM DM_ACTIVITY
            WHERE well_id = ?
            GROUP BY activity_phase
            ORDER BY MIN(time_from)
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def search_wells_text(self, search_query: str) -> list[dict]:
        param = f"%{search_query}%"
        sql = """
            SELECT
                well_id, well_legal_name, well_common_name,
                field_name, well_operator,
                loc_country, loc_state, loc_county,
                spud_date, target_formation, is_offshore, well_purpose
            FROM CD_WELL_SOURCE
            WHERE (well_legal_name LIKE ?
               OR well_common_name LIKE ?
               OR field_name LIKE ?
               OR well_operator LIKE ?)
               AND well_legal_name IS NOT NULL
            ORDER BY spud_date DESC
        """
        return await self._driver.query(sql=self._compile(sql), params=(param, param, param, param))

    async def fetch_reference_well(self, well_id: str) -> dict | None:
        rows = await self._driver.query(
            sql=self._compile(
                "SELECT well_legal_name, field_name, target_formation "
                "FROM CD_WELL_SOURCE WHERE well_id = ?"
            ),
            params=(well_id,),
        )
        return rows[0] if rows else None

    async def search_offset_wells(
        self,
        *,
        reference_well_id: str,
        field_name: str | None,
        target_formation: str | None,
        max_wells: int,
    ) -> list[dict]:
        where_clauses = ["well_legal_name IS NOT NULL", "well_id != ?"]
        params: list[str] = [reference_well_id]
        if field_name:
            where_clauses.append("field_name = ?")
            params.append(field_name)
        if target_formation:
            where_clauses.append("target_formation = ?")
            params.append(target_formation)
        sql = f"""
            SELECT TOP {int(max_wells)}
                well_id, well_legal_name, well_common_name,
                field_name, well_operator,
                loc_country, loc_state, loc_county,
                spud_date, target_formation, is_offshore, well_purpose
            FROM CD_WELL_SOURCE
            WHERE {' AND '.join(where_clauses)}
            ORDER BY spud_date DESC
        """
        return await self._driver.query(sql=self._compile(sql), params=tuple(params))

    async def get_well_name(self, well_id: str) -> str:
        try:
            rows = await self._driver.query(
                sql=self._compile("SELECT well_legal_name FROM CD_WELL_SOURCE WHERE well_id = ?"),
                params=(well_id,),
            )
            if rows and rows[0].get("well_legal_name"):
                return rows[0]["well_legal_name"]
        except Exception:
            logger.warning("get_well_name lookup failed", exc_info=True, extra={"well_id": well_id})
        return well_id

    async def apply_spud_fallback(self, rows: list[dict]) -> None:
        needs_fallback = [r for r in rows if r.get("spud_date") is None]

        if not needs_fallback:
            return

        well_ids = list({r["well_id"] for r in needs_fallback if r.get("well_id")})
        if not well_ids:
            return

        placeholders = ",".join(["?"] * len(well_ids))
        fallback_rows = await self._driver.query(
            sql=self._compile(
                "SELECT well_id, MIN(time_from) AS first_activity "
                f"FROM DM_ACTIVITY WHERE well_id IN ({placeholders}) GROUP BY well_id"
            ),
            params=tuple(well_ids),
        )
        fallback_map = {
            r["well_id"]: r["first_activity"]
            for r in fallback_rows
            if r.get("first_activity") is not None
        }
        for r in needs_fallback:
            resolved = fallback_map.get(r.get("well_id"))
            if resolved is not None:
                r["spud_date"] = resolved
