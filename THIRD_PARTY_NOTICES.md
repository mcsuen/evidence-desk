# Third-party notices

The interface design is original to PITR. Dependencies retain their respective licenses.

- React, React Router, TanStack Query, Radix Primitives and cmdk: MIT, installed through npm with package licenses.
- React Flow (`@xyflow/react`): MIT. ELK.js: EPL-2.0. Used for the restored execution and relationship graphs; notices are retained in `web/public/third-party` and the installed packages.
- Apache ECharts and PDF.js: Apache-2.0; used for on-demand report charts and original-page reading.
- Fontsource IBM Plex Sans / Mono and Noto Sans SC / Serif SC: supplied under their package licenses (OFL / Apache-2.0).
- Noto Sans CJK SC 2.004: SIL Open Font License 1.1, downloaded from [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk/tree/Sans2.004); the installer retains LICENSE.txt beside the font. SHA-256 is pinned in the installer.
- LibreOffice 26.2.6: official unmodified distribution from The Document Foundation, installed project-locally with upstream license files and checksum verification. See [LibreOffice licensing](https://www.libreoffice.org/about-us/licenses/).
- python-docx: MIT. XlsxWriter: BSD-2-Clause. pypdf: BSD-3-Clause. pdfplumber: MIT. PDFium and its bundled components retain the licenses distributed with pypdfium2.

## Preserved local news experiment

- Laya SDK: Apache-2.0, pinned to `573e5b62696ba441230cd6be71d593331b5d23af`: [source](https://github.com/NandhaKishorM/laya).
- Laya multilingual weights: Apache-2.0 per [model card](https://huggingface.co/convaiinnovations/laya), revision `1c5edc17a7acd8701df6fc341c0d179f1c62c982`.
- Multilingual E5 small weights: MIT per [model card](https://huggingface.co/intfloat/multilingual-e5-small), revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`.

News models are downloaded only on explicit installation and are not distributed with this repository. Publisher materials retain their own ownership; synthetic benchmark material is explicitly labeled and does not impersonate real disclosures.
