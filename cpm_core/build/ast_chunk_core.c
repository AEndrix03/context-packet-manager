/*
 * ast_chunk_core.c
 *
 * Core C routines for the cAST chunking algorithm used in CPM.
 * No external dependencies — tree-sitter parsing is handled on the Python side;
 * this module only receives pre-computed byte ranges and sizes.
 *
 * Exported symbols
 * ----------------
 *   nws_count(src, start, end)         -> int
 *   cast_merge(starts, ends, nws, n,
 *              max_chunk_size,
 *              out_starts, out_ends)   -> int   (number of chunks written)
 */

/* --------------------------------------------------------------------------
 * nws_count
 *
 * Count non-whitespace bytes in src[start .. end).
 * Used by the Python traversal to measure each AST node without crossing
 * the Python/C boundary for every character.
 * -------------------------------------------------------------------------- */
int nws_count(const char *src, int start, int end)
{
    int n = 0;
    for (int i = start; i < end; i++) {
        unsigned char c = (unsigned char)src[i];
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r')
            n++;
    }
    return n;
}

/* --------------------------------------------------------------------------
 * cast_merge
 *
 * Greedy merge of N pre-collected atomic nodes into variable-size chunks.
 *
 * The algorithm (cAST, Zhang et al. 2025):
 *   - Walk the atomic node list left to right.
 *   - Accumulate nodes into a "current chunk" as long as their combined
 *     non-whitespace character count stays within max_chunk_size.
 *   - When adding the next node would exceed the budget, flush the current
 *     chunk and start a new one.
 *   - A single node whose own nws count exceeds max_chunk_size is emitted
 *     as a solo chunk (forced split — never drop content).
 *
 * Parameters
 * ----------
 * nodes_start    int[n]   start byte of each atomic node (inclusive)
 * nodes_end      int[n]   end   byte of each atomic node (exclusive)
 * nodes_nws      int[n]   non-whitespace char count of each node
 * n              number of input nodes
 * max_chunk_size budget in non-whitespace characters
 * out_starts     int[n]   output: chunk start bytes  (pre-allocated by caller)
 * out_ends       int[n]   output: chunk end bytes    (pre-allocated by caller)
 *
 * Returns the number of chunks written into out_starts / out_ends.
 * -------------------------------------------------------------------------- */
int cast_merge(
    const int *nodes_start,
    const int *nodes_end,
    const int *nodes_nws,
    int        n,
    int        max_chunk_size,
    int       *out_starts,
    int       *out_ends)
{
    if (n <= 0)
        return 0;

    int count   = 0;
    int cur_s   = nodes_start[0];
    int cur_e   = nodes_end[0];
    int cur_nws = nodes_nws[0];

    for (int i = 1; i < n; i++) {
        int ns = nodes_nws[i];

        if (cur_nws + ns <= max_chunk_size) {
            /* Merge: extend the current chunk to cover this node. */
            cur_e    = nodes_end[i];
            cur_nws += ns;
        } else {
            /* Flush current chunk and start a new one. */
            out_starts[count] = cur_s;
            out_ends[count]   = cur_e;
            count++;

            cur_s   = nodes_start[i];
            cur_e   = nodes_end[i];
            cur_nws = ns;
        }
    }

    /* Flush the last chunk. */
    out_starts[count] = cur_s;
    out_ends[count]   = cur_e;
    count++;

    return count;
}