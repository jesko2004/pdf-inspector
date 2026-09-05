# PDF Inspector

Fast PDF classification and region-based text extraction for Node.js/Bun. Native Rust performance via [napi-rs](https://napi.rs).

## Features

- **Smart classification** — text-based / scanned / image-based / mixed in ~10–50ms, with a confidence score and per-page OCR routing.
- **Region-based extraction** — pull text from bounding boxes with per-region quality checks (`needsOcr`).
- **Layout-aware** — multi-column reading order, position and font info per text item, RTL support.
- **Robust text decoding** — CID/Type0 fonts via ToUnicode CMaps, plus automatic flagging of broken encodings so callers can fall back to OCR.
- **Lightweight** — native Rust core via napi-rs, no ML models, no external services; ~5–6 MB platform binary, TypeScript definitions included.

## Install

```bash
git clone https://github.com/jesko2004/pdf-inspector.git
cd pdf-inspector/napi
npm install
npm run build
```

## API

All public page inputs and result fields are 1-indexed. The first page is `1`,
and passing `0` throws an error.

### `classifyPdf(buffer: Buffer): PdfClassification`

Classify a PDF as TextBased, Scanned, Mixed, or ImageBased (~10-50ms). Returns which pages need OCR.

```typescript
import { classifyPdf } from './index.js'
import { readFileSync } from 'fs'

const pdf = readFileSync('document.pdf')
const result = classifyPdf(pdf)

console.log(result.pdfType)        // "TextBased" | "Scanned" | "Mixed" | "ImageBased"
console.log(result.pageCount)      // 42
console.log(result.pagesNeedingOcr) // [5, 12, 15] (1-indexed)
console.log(result.confidence)     // 0.875
```

### `extractTextInRegions(buffer: Buffer, pageRegions: PageRegions[]): PageRegionTexts[]`

Extract text within bounding-box regions from a PDF. Designed for hybrid OCR pipelines where a layout model detects regions in rendered page images, and this function extracts text from the PDF structure for text-based pages — skipping GPU OCR.

Each region result includes a `needsOcr` flag that signals unreliable extraction (empty text, GID-encoded fonts, garbage text, encoding issues). When the cause is a suspected garbled text layer, `ocrReason` is set to `"suspected_garbled_text"`.

```typescript
import { extractTextInRegions } from './index.js'

const result = extractTextInRegions(pdf, [
  {
    page: 1, // 1-indexed
    regions: [
      [0, 0, 300, 400],    // [x1, y1, x2, y2] in PDF points, top-left origin
      [300, 0, 612, 400],
    ]
  }
])

for (const region of result[0].regions) {
  if (region.needsOcr) {
    // Unreliable text — send this region to OCR instead
  } else {
    console.log(region.text) // Extracted text in reading order
  }
}
```

## Types

```typescript
interface PdfClassification {
  pdfType: string          // "TextBased" | "Scanned" | "Mixed" | "ImageBased"
  pageCount: number
  pagesNeedingOcr: number[] // 1-indexed page numbers
  confidence: number        // 0.0 - 1.0
}

interface PageRegions {
  page: number              // 1-indexed
  regions: number[][]       // [[x1, y1, x2, y2], ...] in PDF points, top-left origin
}

interface PageRegionTexts {
  page: number
  regions: RegionText[]
}

interface RegionText {
  text: string
  needsOcr: boolean         // true when text is unreliable
  ocrReason?: string        // "suspected_garbled_text" when known
}
```

## License

MIT
