"""Data layer for the Content_Eval_System (content-eval-model).

Holds the pluggable source-connector layer (:mod:`app.data.connectors`) and the
committed/cached ``Source_Snapshot`` fixtures it reads. This package sits
*upstream* of the pure :mod:`app.domain.features` module: connectors turn one
Open_Data_Source into partial feature mappings, while feature derivation stays
fetch-free. Nothing here performs a live network fetch at import or during a
normal read -- a live fetch happens only in the out-of-build
``scripts/refresh_source_snapshots.py`` step (R9.4).
"""
