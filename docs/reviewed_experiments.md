# 初回の考察を先行する実験

全96条件について各1試行を先に実行する。その後、全条件のMarkdown考察・技術検査・根拠付きの妥当性判断を終えてから、各条件の本計測10成功へ進む。初回は10回に含めない。最大3並列。初回フェーズでは未レビューの条件があっても別条件の初回を続けるが、反復は開始しない。

保存先はpilots/<条件>/run-01/<規定名>.json、reviews/<条件>/review.md、reviews/<条件>/evidence.json、reviews/<条件>/decision.json。成功した本計測はトップ階層run-01〜run-10へ統合し、measurements/<条件>に元metadata/失敗試行を残す。本計測CSV・失敗率には本計測の全試行を含め、初回は別集計。

技術検査の通過だけでは反復しない。考察には再生、CC/netem実設定、TCPのセッション・DASHソケット対応、欠損/鮮度、Guardrail動作、QoEを含め、観測と原因仮説を分ける。好成績のみを選別しない。単独試行から効果や有意差を断定しない。

decision.jsonは考察した担当者（この作業ではCodex）が作成する。ユーザーへ逐次承認を求める仕組みではない。status=approved/hold、condition、reason、reviewer、log_sha256、batch_sha256を記録する。未レビュー・保留・技術検査失敗・ログ/設定の改変では10回を開始できない。実行前に初回と現在のソース・動画・Dockerイメージの一致も再検証する。追加修正が必要なら別バッチで再検証し、異なるコードを混ぜない。

```bash
/tmp/gp-audit-venv/bin/python scripts/run_reviewed_matrix.py \
  --runner scripts/run_full_matrix.py \
  --profiles experiments/netem_profiles.json \
  --media-dir /home/l0gic/abr-pretest/dash/test2 \
  --image gp-reviewed-20261003 \
  --results-dir results/reviewed-new-batch --workers 3 --phase pilots \
  --first cc-cubic_abr-throughput_signals-none_netem-high-rtt-loss \
  --first cc-cubic_abr-throughput_signals-loss_netem-high-rtt-loss \
  --first cc-bbr_abr-throughput_signals-none_netem-high-rtt-loss
```

本計測では検証済みソースをコピーして--runner/--profilesにその固定パスを使い、--imageには完全なイメージIDを使う。既存results-dirへ再実行しない。

現在の初回6件の考察はresults/initial-reviews-20261003/initial-review.md。旧collectorの対象HTTPソケットがDASHかの裏付けが不足し保留した。collectorを修正し、19件のテスト、実TCP_INFO/WebSocket統合、3並列スモークと未レビュー時の停止を検証した。

初回の全長3条件比較で、要求されたRepresentationを読むgetCurrentBitrateInfoSafeがlastVideoBitrateInfoを上書きし、表示品質0・記録bitrate=品質1となる不整合を発見した。この読み取りを副作用なしに変更し、表示済み品質の記録はQUALITY_CHANGE_RENDEREDだけが更新する。品質要求ログはdash.js 5のold/newRepresentationも記録する。起動はcurrentTimeの正値を条件とせず最初のPLAYBACK_PLAYINGを記録する。

この修正は低ビットレートを改善するためのABR調整ではなく、要求品質と表示品質の測定混同を解消するもの。旧3条件は保留・別保存し、異なるソースとして再検証する。表示品質とbitrateInfo.qualityIndexの一致も技術検査へ追加。20件の回帰テストと実Chromeで要求品質1を読んでも表示品質0のビットレート177434bpsが変わらないことを確認した。

時間加重平均は既知の表示品質ビットレートをHEARTBEAT間の壁時計時間で加重した値。表示品質が不明な起動前区間は含めない。動画フレームごとの精密な積分ではなく、1秒間隔の観測値である。再生中HEARTBEATの算術平均Mbpsも別列に保存する。旧データの定義を遡って変更して混ぜない。

現在の初回計測はresults/all-first-20261003。既存の有効な初回3条件はソース・動画・イメージの一致を検証して取り込み、残り93条件を3並列で実行する。以前開始した10回反復は中断し、results/reviewed-matrix-v2-20261003に別保存した。完了した3試行と中断した3試行は新しい本計測へ含めない。

--phase pilotsは全条件の初回終了後に終了する。first-pass-coverage.csv、phase-status.json、pilot-analysis/に全条件の初回結果・失敗・比較を保存する。全初回と全考察が揃うまでは、--phase allでも反復を起動できない。--phase measurementsは初回と考察の不足があれば開始を拒否する。

固定アプリケーションソースはresults/audit-20261003/reviewed-frozen-v2、固定イメージはsha256:eed7db75e99f9277cffe614dbcd1b4d9e1f1bb9f11ac61ef511be7c549d241eb。現在の実行コントローラはresults/audit-20261003/all-first-controller。再現用コマンド：

```bash
/tmp/gp-audit-venv/bin/python results/audit-20261003/all-first-controller/run_reviewed_matrix.py \
  --runner results/audit-20261003/reviewed-frozen-v2/scripts/run_full_matrix.py \
  --profiles results/audit-20261003/reviewed-frozen-v2/experiments/netem_profiles.json \
  --media-dir /home/l0gic/abr-pretest/dash/test2 \
  --image sha256:eed7db75e99f9277cffe614dbcd1b4d9e1f1bb9f11ac61ef511be7c549d241eb \
  --results-dir results/all-first-new-batch --workers 3 --phase pilots \
  --import-pilots results/reviewed-matrix-v2-20261003
```

順序の回帰検証を含む23テストが通過した。2条件の短い実TCPスモークでは初回2件のみ完了、本計測0件で終了した。これは本計測にも全長初回にも含めない。


結果バッチ名はresults/YYMMDD_Nとする。日付は日本時間、Nは当日の計測番号（1から連番）。現在のバッチはresults/261003_1。QoEログの規定ファイル名は維持する。
