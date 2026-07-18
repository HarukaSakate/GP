# TCP State-Aware ABR 妥当化検討・実装設計書

## 1. 文書の目的

本書は、`/home/l0gic/abr-pretest` の既存実験環境を前提に、TCP 状態を補助信号として用いる `TCP State-Aware ABR` の妥当性を整理し、実装可能な範囲へ設計を落とし込むための文書である。

本テーマは着想として妥当だが、そのままでは成立しない前提がある。特に重要なのは次の2点である。

- 現在の実験系は `HLS + hls.js` ではなく `MPEG-DASH + dash.js` である
- ブラウザ JavaScript から Linux TCP 状態を直接取得することはできない

したがって本設計では、「サーバまたは実験ホスト側で TCP 状態を観測し、それを別チャネルでプレイヤへ渡す」構成を前提とする。

## 2. 結論

`TCP State-Aware ABR` は、研究テーマとしては十分に妥当である。ただし、以下の条件を満たす場合に限る。

1. TCP 状態は ABR の主入力ではなく、既存 ABR の補助信号として使う
2. TCP 状態取得経路を、HTTP セグメント転送経路とは別に設計する
3. CUBIC と BBR で信号の意味が異なることを明示し、同一ルールを盲目的に適用しない
4. ベースライン ABR と比較可能な形で QoE を評価する

逆に、次の主張は避けるべきである。

- `TCP 状態が見えれば輻輳を正確に予測できる`
- `cwnd が大きいほど常に上位ビットレートを選ぶべき`
- `BBR と CUBIC で同じ閾値設計がそのまま使える`

本提案の価値は、帯域推定だけでは遅れて見える輻輳兆候を、`RTT 増加` や `再送増加` といった輸送層信号で早めに検出し、過度な品質上げを抑える点にある。

## 3. 現行環境との整合

### 3.1 現在のリポジトリ実態

`/home/l0gic/abr-pretest` では、少なくとも以下の構成が確認できる。

- プレイヤ: `web/player.html`
- 再生制御: `dash.js`
- 配信方式: `MPEG-DASH`
- ABR 切替: `abrThroughput`, `abrBola`
- ログ取得: `START`, `QUALITY_CHANGE_RENDERED`, `PLAYBACK_WAITING`, `PLAYBACK_STALLED`, `PLAYBACK_PLAYING`, `PLAYBACK_ENDED`, `HEARTBEAT`
- 輻輳制御比較: `CUBIC`, `BBR`
- ネットワーク変動: `tc/netem`, `toggle_bw.sh`

したがって、設計対象は `dash.js ベースの ABR 拡張` とするのが自然であり、HLS 前提の設計は現状と整合しない。

### 3.2 実装対象の修正方針

旧案の `HLS + hls.js` 前提は撤回し、次に統一する。

- プレイヤ層: `dash.js`
- 配信層: `HTTP/1.1 over TCP + MPEG-DASH`
- TCP 観測: Linux 側の eBPF もしくは `TCP_INFO`
- プレイヤへの通知: WebSocket

## 4. 想定ユースケース

### 4.1 解きたい問題

既存の Throughput-based ABR は、帯域低下や再送増加が起きた後に推定値へ反映されやすい。一方 BOLA はバッファを重視するため、即時の輸送層変化には鈍い場合がある。

ここで、TCP 側の兆候を補助的に使うことで、以下を狙う。

- RTT 膨張時に早めに上げ過ぎを抑える
- 再送増加時に品質上昇を保留する
- 輻輳制御方式ごとの差を、アプリ層に観測可能な信号として比較する

### 4.2 期待できる効果

- stall 発生前の予防的ダウングレード
- 不要な oscillation の低減
- CUBIC と BBR のクロスレイヤ差の可視化

### 4.3 期待し過ぎてはいけない点

- TCP 状態だけで将来スループットを完全予測することはできない
- ABR 判断の最終責任は、依然としてアプリ層の再生状況とバッファに置くべきである
- WebSocket で渡す信号は補助観測であり、セグメント接続そのものの TCP 制御に介入するわけではない

## 5. 成立条件と制約

### 5.1 最大の成立条件

ブラウザは HTTP セグメント転送に使っている TCP ソケットの `cwnd`, `srtt`, `retrans` を直接読めない。したがって、`TCP State-Aware ABR` を成立させるには、観測主体をブラウザの外へ置く必要がある。

### 5.2 実装上の制約

- WebSocket 接続と DASH セグメント接続は通常別 TCP 接続
- そのため、観測した TCP 状態と「どの再生セッションの ABR に渡すか」の対応付けが必要
- BBR では `cwnd` の意味が CUBIC より弱く、`delivery rate` や `RTT inflation` の方が解釈しやすい
- eBPF は環境依存があるため、フォールバック経路を用意すべき

### 5.3 設計上の判断

初期実装では、単一クライアント・単一再生セッションに限定する。この前提なら、`対象クライアント IP + サーバポート + 観測時刻` による紐付けで十分に実験できる。

## 6. 提案アーキテクチャ

```text
Browser (dash.js player)
  ├── HTTP/TCP connection for DASH segments
  ├── WebSocket connection for TCP side-channel
  └── QoE logger
           │
           ▼
Experiment Server
  ├── HTTP server for MPD and segments
  ├── WebSocket signal server
  ├── TCP metrics collector
  │     ├── eBPF sock_ops / tcp trace
  │     └── or getsockopt(TCP_INFO) fallback
  └── session mapper
```

信号経路は2本に分かれる。

- 本流: DASH セグメント配信
- 側路: TCP 状態の通知

この分離を明示しておくことが、設計の妥当性にとって重要である。

## 7. 観測信号の選定

### 7.1 採用候補

初期実装では以下を候補とする。

- `srtt_us`
- `rtt_min_us`
- `total_retrans`
- `lost_out` または近い損失指標
- `snd_cwnd`
- `packets_out`
- `bytes_acked`
- `delivery_rate` 相当
- `cc` (`cubic` / `bbr`)

### 7.2 ABR で直接使う信号

ABR の入力として優先度が高いのは次である。

- `rtt_inflation = srtt / rtt_min`
- `retransmissions_delta`
- `delivery_rate_bps`
- `signal freshness`
- `cc`

`cwnd` は参考値として保持するが、初期ルールの主判定に使いすぎない。

### 7.3 信号の解釈

- `rtt_inflation` は queue 蓄積の兆候として使いやすい
- `retransmissions_delta` は損失兆候として解釈しやすい
- `delivery_rate_bps` は BBR 環境で比較的意味を持ちやすい
- `cwnd` は CUBIC では見やすいが、BBR では単独解釈を避ける

## 8. dash.js 側の適用方針

### 8.1 基本方針

既存の `abrThroughput` または `abrBola` を完全に置き換えるのではなく、`guardrail` を加える形で拡張する。

考え方は以下である。

- ベース選択は既存 ABR に任せる
- TCP 信号が健全ならベース選択をそのまま採用する
- TCP 信号が悪化した場合だけ、上げ抑制または 1 段階ダウンを行う

### 8.2 妥当な理由

この方式なら、既存 ABR の成熟した判断を壊しにくい。研究としても、`baseline` と `TCP-aware guardrail` の比較が明確になる。

### 8.3 避けるべき設計

- TCP 信号だけで representation を直接選ぶ
- BOLA/Throughput の内部ロジックを全面的に捨てる
- `cwnd` 単独で昇降判定を行う

## 9. ABR 判定ルール案

### 9.1 ルールベースの初期版

初期版は次のような閾値ルールで十分である。

```text
baseline = existing_abr_choice()

if tcp_signal is missing or stale:
    use baseline

if cc == cubic:
    if rtt_inflation > 1.5 or retransmissions_delta > 0:
        clamp to max(baseline - 1, lowest)

if cc == bbr:
    if rtt_inflation > 1.4 and delivery_rate_drop is observed:
        clamp to max(baseline - 1, lowest)

if buffer_sec < 4:
    prefer conservative choice

otherwise:
    use baseline
```

### 9.2 ルール設計上の注意

- `stale` な信号は無視する
- 単発イベントではなく短い窓で平滑化する
- CUBIC と BBR で閾値を分ける
- 品質上げは慎重に、品質下げは速めにする

## 10. セッション対応付け

### 10.1 問題

ABR に使う TCP 状態は「その動画再生に対応する HTTP 接続」のものである必要がある。しかし、プレイヤ側の WebSocket 接続は別ソケットである。

### 10.2 初期解

プレイヤが起動時に `session_id` を WebSocket サーバへ送る。

```json
{
  "type": "hello",
  "session_id": "exp-001",
  "client_ip": "203.178.128.214"
}
```

サーバ側では、次の条件で候補ソケットを絞る。

- クライアント IP が一致
- DASH 配信ポートへ接続している
- 直近に bytes_acked の更新がある

### 10.3 妥当性評価

単一クライアント実験では妥当。複数クライアント同時接続を前提にするなら不十分であり、その場合は reverse proxy 側でアクセスログと socket metadata を対応付ける仕組みが必要になる。

## 11. 実装方式

### 11.1 推奨方式

第一候補:

- Linux eBPF で TCP メトリクス観測
- ユーザー空間 collector が 100 ms 周期で集約
- WebSocket で 500 ms 周期配信
- dash.js に custom rule または制約ルールとして接続

### 11.2 フォールバック方式

eBPF が難しい場合は、`TCP_INFO` 取得を使った簡略版で開始してよい。

この場合の利点:

- 実装が軽い
- カーネル依存が相対的に小さい
- 妥当化検討の初期実験として十分

この場合の欠点:

- 取得粒度や項目が制限される
- socket 取得位置によっては可観測性が下がる

## 12. 実装対象の具体化

### 12.1 プレイヤ側

現在の `web/player.html` をベースに、以下を追加する。

- WebSocket クライアント
- `session_id` の生成と送信
- 最新 TCP 信号の保持
- TCP-aware 判定ログ
- ABR 判定と QoE ログの同時記録

### 12.2 サーバ側

追加が必要なもの:

- TCP metrics collector
- WebSocket signal server
- session mapper
- 実験ログ保存

### 12.3 ログ

最低限、以下を時系列で残す。

- representation 選択
- bitrate
- buffer level
- stall count
- stall duration
- startup delay
- TCP snapshot
- TCP snapshot age
- 使用中の CC

## 13. 実験計画

### 13.1 比較軸

- ABR: `Throughput`, `BOLA`
- TCP-aware: `off`, `on`
- CC: `CUBIC`, `BBR`
- ネットワーク条件: 固定帯域、変動帯域、高遅延、損失あり

### 13.2 最低限の実験条件

| ID | rate | delay | loss | 目的 |
| --- | ---: | ---: | ---: | --- |
| S1 | 3 Mbit/s | 50 ms | 0% | 基本条件 |
| S2 | 1 Mbit/s | 50 ms | 0% | 帯域制約 |
| S3 | 3 Mbit/s | 150 ms | 0% | RTT 膨張影響 |
| S4 | 3 Mbit/s | 50 ms | 2% | 再送影響 |
| S5 | 1-3 Mbit/s oscillation | 50 ms | 0% | 変動条件 |

### 13.3 評価指標

- 平均再生ビットレート
- rebuffer 回数
- 総 rebuffer 時間
- bitrate switch 回数
- switch magnitude
- startup delay
- 低品質滞在時間
- TCP 信号欠損率
- TCP 信号鮮度

## 14. リスクと対策

### 14.1 過学習的ルール

特定シナリオだけで効く閾値設計になる恐れがある。

対策:

- ルールは少数特徴量で始める
- CUBIC と BBR を分けて評価する
- ablation を入れる

### 14.2 誤対応付け

別セッションの TCP 状態を参照すると結果が壊れる。

対策:

- 単一クライアントに限定する
- session ログと socket 候補選択ログを残す
- bytes_acked 更新のあるソケットだけ使う

### 14.3 dash.js 連携コスト

dash.js の ABR 拡張点は hls.js より調査が必要な場合がある。

対策:

- 最初は完全 custom ABR ではなく `guardrail` 型で入れる
- ベース ABR の出力と最終出力を両方ログする

### 14.4 eBPF 依存

環境差で詰まる可能性がある。

対策:

- 先に `TCP_INFO` 版の縦切りを作る
- eBPF 版はその後に差し替える

## 15. 最小実装の定義

最初に通すべき縦切りは次である。

1. `dash.js` プレイヤが DASH を再生できる
2. サーバ側で対象 TCP 接続の RTT と再送を取得できる
3. WebSocket で 500 ms ごとに信号をブラウザへ送れる
4. プレイヤログに `QUALITY_CHANGE_RENDERED` と TCP 信号を同時記録できる
5. `rtt_inflation` または `retransmissions_delta` が閾値超過時に 1 段階だけ抑制できる
6. TCP 信号が欠損したら既存 ABR に自動フォールバックできる

この縦切りが完成していれば、研究として最低限の成立性は確保できる。

## 16. 最終判断

本テーマは、`cross-layer ABR` の実験として十分に妥当である。ただし、妥当なのは次の定義に限る。

- `TCP state-aware` は「ブラウザが TCP を直接見る」ことではない
- `TCP state-aware` は「TCP の補助信号を別チャネルで受ける ABR」である
- `TCP-aware ABR` は既存 ABR の代替ではなく拡張として評価する

したがって、研究計画としては採用可能である。実装計画としては、`DASH + dash.js` に統一し、`TCP_INFO または eBPF -> WebSocket -> dash.js guardrail` の順で段階実装するのが最も現実的である。
