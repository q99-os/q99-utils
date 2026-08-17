from typing import Any

from q99_utils.integrations.mappers.openwells_base import OpenWellsAgentMapper
from q99_utils.logger import get_logger

logger = get_logger(__name__)

class OpenWellsEDMMapper(OpenWellsAgentMapper):
    """OpenWells agent mapper for the EDM schema.

    Canonical SQL is written in MSSQL T-SQL. For non-tsql dialects the
    ``_compile`` seam transpiles at execute time, which needs the ``openwells``
    extra (``pip install q99-utils[openwells]``).
    """

    def __init__(
        self,
        driver: Any,
        *,
        dialect: str = "tsql",
    ):
        self._driver = driver
        self._dialect = dialect

    def _compile(self, sql: str) -> str:
        if self._dialect == "tsql":
            return sql
        import sqlglot
        return sqlglot.transpile(sql, read="tsql", write=self._dialect)[0]

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
        sql = """
            SELECT
                activity_id,
                event_id,
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
                service_company
            FROM DM_ACTIVITY
            WHERE
                well_id = ?
            ORDER BY time_from
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_activity_span(self, well_id: str) -> dict | None:
        """First and last activity timestamps. An aggregate rather than a read
        of the log: callers that only need the well's extent shouldn't pay for
        every row."""
        sql = """
            SELECT
                MIN(time_from) AS first_from,
                MAX(time_from) AS last_from,
                MAX(time_to) AS last_to
            FROM DM_ACTIVITY
            WHERE well_id = ? AND time_from IS NOT NULL
        """
        rows = await self._driver.query(sql=self._compile(sql), params=(well_id,))
        return rows[0] if rows else None

    async def fetch_activity_days(self) -> list[dict]:
        """One row per well per calendar day of logged activity, fleet-wide.

        ``day_advanced`` marks days the hole actually deepened — the same test
        the per-well criterion applies row by row, pushed into SQL because the
        alternative is reading the whole fleet's activity log to answer it.
        """
        sql = """
            SELECT
                well_id,
                CAST(time_from AS DATE) AS d,
                MAX(time_from) AS day_last_from,
                MAX(time_to) AS day_last_to,
                MAX(md_to) AS day_max_md,
                MAX(CASE WHEN md_to IS NOT NULL
                          AND (md_from IS NULL OR md_from <> md_to)
                         THEN 1 ELSE 0 END) AS day_advanced
            FROM DM_ACTIVITY
            WHERE time_from IS NOT NULL
            GROUP BY well_id, CAST(time_from AS DATE)
        """
        return await self._driver.query(sql=self._compile(sql), params=())

    async def fetch_events(self, well_id: str) -> list[dict]:
        """The well's events and their declared codes."""
        sql = "SELECT event_id, event_code FROM DM_EVENT WHERE well_id = ?"
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_surveys(self, well_id: str) -> list[dict]:
        """Survey stations, tagged by the ``phase`` of their pass.

        One header per phase — each is a full path, so pooling them interleaves
        into a sawtooth. The current one wins: stations carrying ``offset_north``
        first, then most recently updated. Ordered by the survey's own
        ``sequence_no``, so a sidetrack keeps its running order.
        """
        sql = """
            WITH ranked AS (
                SELECT
                    h.def_survey_header_id,
                    h.phase,
                    ROW_NUMBER() OVER (
                        PARTITION BY h.phase
                        ORDER BY
                            CASE WHEN EXISTS (
                                SELECT 1 FROM CD_DEFINITIVE_SURVEY_STATION o
                                WHERE o.def_survey_header_id = h.def_survey_header_id
                                  AND o.offset_north IS NOT NULL
                            ) THEN 0 ELSE 1 END,
                            h.update_date DESC
                    ) AS rn
                FROM CD_DEFINITIVE_SURVEY_HEADER h
                WHERE
                    h.well_id = ?
                    AND EXISTS (
                        SELECT 1 FROM CD_DEFINITIVE_SURVEY_STATION s
                        WHERE s.def_survey_header_id = h.def_survey_header_id
                    )
            )
            SELECT
                r.phase,
                dss.def_survey_header_id,
                dss.sequence_no,
                dss.md,
                dss.tvd,
                dss.inclination,
                dss.azimuth,
                dss.dogleg_severity,
                dss.offset_north,
                dss.offset_east
            FROM CD_DEFINITIVE_SURVEY_STATION dss
            INNER JOIN ranked r
                ON r.def_survey_header_id = dss.def_survey_header_id
                AND r.rn = 1
            ORDER BY r.phase ASC, dss.sequence_no ASC
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_depth_offset(self, well_id: str) -> float:
        """How much to add to a logged depth before converting it. Coalesced to
        zero: an unset offset is no offset, not a missing depth."""
        rows = await self._driver.query(
            sql=self._compile(
                "SELECT COALESCE(water_depth, 0) AS depth_offset "
                "FROM CD_WELL_SOURCE WHERE well_id = ?"
            ),
            params=(well_id,),
        )
        return rows[0]["depth_offset"] if rows else 0.0

    async def fetch_datum(self, well_id: str) -> list[dict]:
        """Elevation of the well's depth references."""
        sql = """
            SELECT datum_elevation, datum_name, datum_type, is_default
            FROM CD_DATUM
            WHERE well_id = ?
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_formations(self, well_id: str) -> list[dict]:
        """Formation tops actually hit, shallowest first.

        ACTUAL only; PLAN/PROTOTYPE rows are prognoses. On ACTUAL rows the
        ``prognosed_*`` columns carry the picked depth. Sidetracks pick the same
        top twice, so ``wellbore_id`` travels with the row.
        """
        sql = """
            SELECT DISTINCT
                cwf.wellbore_id,
                cwf.formation_name,
                cwf.prognosed_md AS md_top,
                cwf.prognosed_base_md AS md_base,
                cwf.prognosed_tvd AS tvd_top,
                cwf.prognosed_base_tvd AS tvd_base,
                cwf.dip_angle,
                clc.lithology,
                cwf.comments
            FROM CD_WELLBORE_FORMATION cwf
            LEFT JOIN CD_LITHOLOGY_CLASS clc
                ON clc.lithology_id = cwf.lithology_id
            WHERE
                cwf.well_id = ?
                AND cwf.phase = 'ACTUAL'
                AND cwf.formation_name IS NOT NULL
            ORDER BY cwf.prognosed_md ASC
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

    async def fetch_pipe_tally(self, well_id: str) -> list[dict]:
        """Joint-by-joint tally of every pipe string run in the well.

        One row per piece, so a 6 km string is ~450 rows and a whole well can
        exceed a thousand — ask for it when the question is about individual
        joints, not about a string's overall length.

        Reading it: ``cum_length`` is the depth at the **bottom** of each
        piece, so a piece spans ``cum_length - length`` to ``cum_length``.
        A null ``joint_number`` marks a piece with a function rather than a
        place in the string's numbering — shoe, float collar, pup, crossover,
        marker joint — and ``comp_name``/``description`` say which.
        ``assembly_name`` is the operator's own string name; there is no fixed
        vocabulary, so read it as given rather than matching on it.

        The flags are sparse by design — ``centralize``, ``is_out`` and
        ``is_replaced`` are set only on the pieces they apply to, so a null is
        a "no", not a gap. Per-joint serial numbers and connection types are
        not selected: the one reference tenant filled them on 5 and 1 rows out
        of 158,328, and every null still costs the model a key on every row.
        """
        sql = """
            SELECT
                a.assembly_name,
                a.string_type,
                r.run_tally_type,
                r.date_report,
                r.tally_by,
                r.is_top_down,
                t.sequence_no,
                t.joint_number,
                t.length,
                t.cum_length,
                t.is_out,
                t.is_replaced,
                t.centralize,
                t.letter_code,
                CAST(t.comments AS NVARCHAR(MAX)) AS comments,
                d.comp_name,
                d.description,
                d.nominal_size,
                d.weight,
                d.grade,
                d.range,
                d.id_drift
            FROM DM_PIPE_TALLY t
            LEFT JOIN DM_PIPE_DATA d
                ON d.pipe_data_id = t.pipe_data_id
            LEFT JOIN DM_PIPE_RUN r
                ON r.pipe_run_id = t.pipe_run_id
            LEFT JOIN CD_ASSEMBLY a
                ON a.assembly_id = r.assembly_id
            WHERE t.well_id = ?
            ORDER BY r.date_report, t.cum_length
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_bha(self, well_id: str) -> list[dict]:
        sql = """
            SELECT
                ca.assembly_name,
                cbcb.bit_size,
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
                cac.od_body,
                cac.id_body,
                cac.length,
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
        """NPT events. ``npt_net_time`` is the operator's own accounting, bounded
        by the event window — an event cannot bill more time than it lasted.

        Placement is the caller's: ``first_activity_id`` points at the activity
        the event began on. Resolving it here means joining the activity log and
        carrying an ntext description through that join, which costs ~25 s a well
        on a remote tenant against 0.6 s without it.
        """
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
                CASE
                    WHEN ef.date_failure_start IS NOT NULL
                     AND ef.date_failure_end > ef.date_failure_start
                     AND ef.npt_net_time > DATEDIFF(SECOND, ef.date_failure_start, ef.date_failure_end) / 3600.0
                    THEN DATEDIFF(SECOND, ef.date_failure_start, ef.date_failure_end) / 3600.0
                    ELSE ef.npt_net_time
                END AS npt_net_time,
                ef.npt_nested_time,
                ef.npt_level,
                ef.equip_fail_type,
                ef.contractor_name,
                ef.npt_total_cost_net,
                ef.failure_total_cost,
                ef.event_id,
                ef.first_activity_id,
                ef.last_activity_id
            FROM DM_OPER_EQUIP_FAIL ef
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
        """Solids-control runs, both machines in one series.

        A hydrocyclone reports ``press_op``, a centrifuge ``rpm``; each branch
        pads the other's column with a typed NULL and ``equipment_type`` says
        which to read. The second branch is aliased to the first's output names
        so the UNION's positional pairing reads instead of counts.
        """
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
                CAST(NULL AS FLOAT) AS rpm
            FROM DM_HYDROCLONE_OP
            WHERE well_id = ?
            UNION ALL
            SELECT
                'centrifuge'        AS equipment_type,
                date_op             AS date_op,
                ROUND(md_op, 2)     AS md_op,
                duration            AS duration,
                density_feed        AS density_feed,
                density_overflow    AS density_overflow,
                density_underflow   AS density_underflow,
                feed_flowrate       AS flowrate_feed,
                overflow_flowrate   AS flowrate_overflow,
                underflow_flowrate  AS flowrate_underflow,
                CAST(NULL AS FLOAT) AS press_op,
                rpm                 AS rpm
            FROM DM_CENTRIFUGE_OP
            WHERE well_id = ?
            ORDER BY date_op
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id, well_id))

    async def fetch_plan_operations(self, well_id: str) -> list[dict]:
        """Planned operations for the well, across every plan. ``well_plan_id``
        joins to :meth:`fetch_plan_headers`, which the caller picks from."""
        sql = """
            SELECT
                well_plan_id,
                md_from,
                md_to,
                activity_memo,
                sequence_no,
                activity_phase,
                target_duration
            FROM DM_WELL_PLAN_OP
            WHERE
                well_id = ?
            ORDER BY sequence_no
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_plan_headers(self, well_id: str) -> list[dict]:
        """One row per program filed against the well: what kind of job it is,
        which revision, when it was planned. Which one to draw is the caller's
        call — see the operations."""
        sql = """
            SELECT
                well_plan_id,
                job_type,
                version,
                planning_start_date,
                expected_work_start_date
            FROM DM_WELL_PLAN
            WHERE
                well_id = ?
        """
        return await self._driver.query(sql=self._compile(sql), params=(well_id,))

    async def fetch_wells(self) -> list[dict]:
        """Every named well in the tenant. Wells with neither name are dropped:
        there is nothing to show or search for."""
        sql = """
            SELECT
                well_id,
                COALESCE(well_common_name, well_legal_name) AS name,
                field_name,
                well_operator,
                loc_country,
                loc_state,
                loc_county,
                target_formation,
                spud_date,
                water_depth
            FROM CD_WELL_SOURCE
            WHERE COALESCE(well_common_name, well_legal_name) IS NOT NULL
        """
        return await self._driver.query(sql=self._compile(sql), params=())

    async def fetch_npt_last_end(self, well_ids: list[str] | None = None) -> list[dict]:
        """Latest NPT-event end per well; the whole fleet when no ids are given.

        The one question a status check asks of NPT, answered as an aggregate:
        callers that only need "is this well still down" shouldn't read every
        event to find out.
        """
        where, params = "", ()
        if well_ids is not None:
            if not well_ids:
                return []
            where = f"WHERE well_id IN ({', '.join(['?'] * len(well_ids))})"
            params = tuple(well_ids)
        sql = f"""
            SELECT well_id, MAX(date_failure_end) AS last_fail_end
            FROM DM_OPER_EQUIP_FAIL
            {where}
            GROUP BY well_id
        """
        return await self._driver.query(sql=self._compile(sql), params=params)

    async def search_wells_text(self, search_query: str) -> list[dict]:
        """Wells matching ``search_query`` on any name or identifier."""
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
               OR well_operator LIKE ?
               OR well_uwi LIKE ?
               OR well_id LIKE ?)
               AND well_legal_name IS NOT NULL
            ORDER BY spud_date DESC
        """
        return await self._driver.query(sql=self._compile(sql), params=(param,) * 6)

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

    async def get_well_names(self, well_ids: list[str]) -> dict[str, str]:
        """well_id → legal name, for the ids that have one. One query however many
        wells are asked for."""
        if not well_ids:
            return {}
        placeholders = ", ".join(["?"] * len(well_ids))
        rows = await self._driver.query(
            sql=self._compile(
                f"SELECT well_id, well_legal_name FROM CD_WELL_SOURCE "
                f"WHERE well_id IN ({placeholders})"
            ),
            params=tuple(well_ids),
        )
        return {r["well_id"]: r["well_legal_name"] for r in rows if r.get("well_legal_name")}

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
