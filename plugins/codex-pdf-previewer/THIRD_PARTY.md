# Third-party components

Mozilla PDF.js / pdfjs-dist **5.6.205**, Apache License 2.0.

Upstream: https://github.com/mozilla/pdf.js

The files in `vendor/pdfjs/` are an unmodified subset of the PDF.js distribution: the main module, worker, CMaps, standard fonts, Wasm decoders, viewer CSS and images. See `vendor/pdfjs/LICENSE` and `vendor/pdfjs/package.json` for the distribution's license and metadata. Additional font and decoder licenses are preserved in their respective directories. Source-map build artifacts are not included.

The original launcher, reader and packaging are provided under the repository's MIT license. No user document, document screenshot, local session, or manuscript source is distributed with the plugin.
