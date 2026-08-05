# q99-utils

Libreria de herramientas comunes entre los microservicios de Q99

```
q99_utils/
├── enums/              enumeraciones compartidas, una por módulo
│   ├── source.py               SourceEnum
│   ├── database_backend.py     DatabaseBackendEnum
│   └── integration_type.py     IntegrationTypeEnum
├── models/             payloads que se intercambian con el User Manager
│   ├── onboarding.py           OnboardingData
│   ├── chat.py                 UMMessage
│   ├── telemetry.py            UMTrace, UMTraceGroup
│   ├── exports.py              UMExport
│   ├── reports.py              UMReport, UMReportSection
│   └── scheduling.py           UMCrontab, UMTaskSchedule
├── integrations/       integraciones con fuentes externas (tiene su propio README)
├── um_sdk.py           cliente HTTP del User Manager
├── environment.py      variables de entorno
└── logger.py           logger de librería (NullHandler, no configura nada)
```

Los enums se re-exportan desde `q99_utils.models`, así que
`from q99_utils.models import SourceEnum` sigue andando. En código nuevo
conviene `from q99_utils.enums import SourceEnum`.

## Instalación

```
q99-utils              # base
q99-utils[google]      # + la integración de Google Drive
```
