from impact import summarize_impact


def test_summarize_impact_detects_major_and_minor_signals() -> None:
    diff_text = """
- export function login(username, password) {
+ export function login(credentials) {
+ export function listUsers() {
  return true;
}
"""
    summary = summarize_impact(diff_text)
    assert summary.major_signals >= 1
    assert summary.minor_signals >= 1
    assert any("signature_changes" in reason for reason in summary.top_reasons)


def test_summarize_impact_tracks_patch_lines() -> None:
    diff_text = """
diff --git a/src/private.py b/src/private.py
@@ -1,3 +1,3 @@
-x = compute(a)
+x = compute(a, b)
"""
    summary = summarize_impact(diff_text)
    assert summary.patch_signals >= 1
