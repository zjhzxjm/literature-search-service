# Third-party notices

The query and ranking logic in `src/literature_search_service/search.py` and the reference search function in `tests/integration/test_elasticsearch.py` are adapted from [SciClaims ESSearcher](https://github.com/expertailab/sciclaims-backend/blob/915946f21ef12fb3187ac9e1ed22ce9fcd76768b/sciclaims_backend/processing/es_indexing.py), commit `915946f21ef12fb3187ac9e1ed22ce9fcd76768b`.

Changes include string PMID identifiers, result objects containing document text, input validation and rejection of partial search results. The query body, zero-based ranks and raw scores are preserved for k=1–10. This notice does not select a license for the rest of this project.

## SciClaims — MIT License

Copyright (c) 2025 expert.ai Research Lab

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
