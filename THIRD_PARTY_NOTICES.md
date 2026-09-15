# Third-party notices

The research desk selectively adapts neutral palette and control-state values from the LSEG / Refinitiv Element Framework Halo theme. The project is not affiliated with or endorsed by LSEG.

Source: https://github.com/Refinitiv/refinitiv-ui
Pinned revision: 7cc68865db56b7444b2d08a861e65d8e56633d81 (v7).
Referenced files: packages/halo-theme/src/variants/light/overrides.less; packages/halo-theme/src/palettes/{secondary,typography,core}.less.
The upstream code is Apache-2.0, subject to exceptions identified in its LICENSE.md. A copy is retained in web/public/third-party/halo-LICENSE.md. No Proxima Nova Fin or other restricted LSEG font files are distributed.

Adaptations: scoped CSS variables/neutral palette in web/src/desk/desk.css; Chinese 32px/28px density; separate model, document-diff, and chart semantics. Fonts are installed separately from Fontsource packages (IBM Plex Sans / Noto Sans SC) with their package licenses.

Other runtime dependencies retain their own package licenses. PDF.js and Apache ECharts are not LSEG components. No screenshots or proprietary financial model templates are redistributed as application assets.

## Research execution visualization

- React Flow (`@xyflow/react` 12.11.6): MIT. Source: https://github.com/xyflow/xyflow/tree/main/packages/react. License copy: `web/public/third-party/react-flow-LICENSE.txt`.
- ELK.js (`elkjs` 0.12.0): used under EPL-2.0, one of the package's offered licenses. Unmodified upstream source is available at https://github.com/kieler/elkjs and in the published npm `elkjs@0.12.0` package. License copy: `web/public/third-party/elkjs-LICENSE.md`.
- LangSmith Python SDK 0.12.4: MIT; installed as a Python dependency, not embedded in the frontend. Synchronization is disabled by default.
- OpenTelemetry protobuf definitions (`opentelemetry-proto` 1.44.0): Apache-2.0.

The workflow viewer is a read-only projection of PITR's local execution ledger. No LangSmith or Langfuse branding, proprietary UI assets, or hosted service is bundled.
