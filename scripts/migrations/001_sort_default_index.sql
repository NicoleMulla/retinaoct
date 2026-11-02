-- Restores the composite index for the default results sort.
--
-- functions/api/search.js orders by `has_biomarkers DESC, biomarker_count DESC,
-- id` (SORTS.relevant). With no matching index, SQLite scans and sorts the
-- whole images table to return 24 rows: 156,566 row reads per page load at the
-- current corpus size, against 24 with the index. D1's free tier allows 5
-- million reads a day, so this is the difference between ~32 page views and
-- effectively unlimited browsing.
--
-- Added directly to D1 by commit 976571d and lost when the images table was
-- rebuilt from olives_d1.sql, which only carries eight indexes. Now also in
-- scripts/build_olives_index.py so a rebuild keeps it.
CREATE INDEX IF NOT EXISTS idx_img_sort_default
  ON images(has_biomarkers DESC, biomarker_count DESC, id ASC);
