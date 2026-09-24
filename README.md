

# 📄 README.md

## 概要

本研究の主目的は、**ブラウザ上のABR（Adaptive Bitrate）ロジックが、
通常はブラウザから取得できないTCPの内部情報へアクセスするためのAPIを実装すること**
である。

Linuxの`TCP_INFO`からRTT、CWND、再送、推定パケットロス率などを取得し、
再生セッションに対応付けたうえで、WebSocket APIを通してdash.jsプレイヤへ提供する。
プレイヤは受信したTCPメトリクスを画面に表示でき、さらに各メトリクスを
ABR判断に使用するかどうかをブラウザ上で選択できる。

このAPIによって、アプリケーション層のスループットやバッファだけを参照する
従来のABRに、トランスポート層の状態を入力できるcross-layerな実験基盤を構築する。

本プロジェクトで行うThroughput-based ABRとBOLA、およびCUBICとBBRの比較は、
それ自体を最終目的とするものではない。これらの比較実験は、実装したAPIから得られる
TCP内部情報がABRの品質選択やQoEへ与える効果を検証するために実施する。

> ここでいう「TCP内部情報へアクセスするAPI」とは、ブラウザがOSのTCPソケットを
> 直接読み取るAPIではない。配信サーバ側で対象TCP接続を観測し、正規化した情報を
> WebSocketでABRへ公開するブラウザ向けAPIを指す。

---

## 🎯 目的

### 主目的

* LinuxのTCP内部情報を取得し、ABRから利用可能な形式へ正規化する
* TCPメトリクスを再生セッションへ対応付けて配信するWebSocket APIを実装する
* RTT、CWND、再送、推定パケットロス率などをブラウザから観測可能にする
* 各TCPメトリクスをABR判断に使用するか、ブラウザ上で個別に選択可能にする
* TCP情報が欠損または期限切れの場合に、既存ABRへ安全にフォールバックさせる

### APIの有効性を確認するための評価

* TCP情報を使用しない通常ABRとTCP-aware ABRを同一条件で比較する
* Throughput-based ABRとBOLAに対するTCPメトリクスの効果を確認する
* CUBICとBBRでTCPメトリクスの意味やABRへの影響がどう異なるかを評価する
* ネットワーク変動下で、品質切替、再生停止、バッファ、QoEへの影響を測定する

---

## 🧪 実験構成

### システム構成

* TCPメトリクスAPI：`scripts/tcp_info_signal_server.py`
* TCP情報取得：Linux `TCP_INFO`
* APIトランスポート：WebSocket（`tcp_metrics` JSON）
* DASH配信：TCP観測機能を持つHTTP/1.1サーバ（nginxは従来比較用）
* APIクライアント・ABR：dash.jsを使用するブラウザプレイヤ
* 動画形式：MPEG-DASH
* ネットワーク制御：tc / netem（Linux）

---

## 🎬 使用動画

Big Buck Bunny を使用し、以下の解像度で用意：

* 1080p

---

## ⚙️ 環境構築

### 必要パッケージ

```bash
sudo apt update
sudo apt install -y ffmpeg nginx iproute2 curl
```

---

## 🎞️ 動画の前処理

### GOP・アスペクト比の統一

```bash
ffmpeg -i input.mp4 \
-c:v libx264 -g 60 -keyint_min 60 -sc_threshold 0 \
-vf "setsar=1,setdar=16/9,scale=WIDTH:HEIGHT" \
-c:a aac -b:a 128k \
output.mp4
```

---

## 📦 DASH化


```bash
ffmpeg -y \
-i bbb_320.mp4 \
-i bbb_720.mp4 \
-map 0:v -map 1:v \
-c copy \
-f dash \
-seg_duration 2 \
-use_template 1 \
-use_timeline 1 \
-adaptation_sets "id=0,streams=v" \
stream.mpd
```

---

## 🌐 配信設定（nginx）

```bash
sudo tee /etc/nginx/conf.d/dash.conf >/dev/null <<'EOF'
types {
    application/dash+xml mpd;
    video/mp4 m4s;
}

server {
    listen 8080 default_server;
    root /var/www/html;

    location / {
        add_header Cache-Control no-cache;
    }
}
EOF
```

```bash
sudo systemctl restart nginx
```

---

python3 -m http.server 8000 --bind 0.0.0.0


## ▶️ プレイヤ（dash.js）

ブラウザからアクセス：

```
http://127.0.0.1:8080/player.html
```

### ABR切替

* `abrThroughput`
* `abrBola`

---

## TCPメトリクスの可視化とTCP-aware ABR

### 概要

ブラウザは、DASHセグメントの通信に使われるLinuxのTCPソケットから
`RTT`や`CWND`を直接取得できない。そのため、本実装では配信サーバ側で
`TCP_INFO`を読み取り、WebSocketを介してブラウザへTCPメトリクスを通知する。

```text
DASHセグメント用TCP接続
  ↓ TCP_INFOを観測
scripts/tcp_info_signal_server.py
  ↓ tcp_metrics JSONをWebSocketで通知
web/player.html
  ├─ TCPメトリクスを画面表示
  └─ 選択されたメトリクスをABR Guardrailで評価
```

TCP情報は既存のThroughputまたはBOLAを置き換えるものではない。
通常のABR判断を基本とし、TCP側で輻輳の兆候を検出した場合にだけ
品質を1段階下げる補助機構として使用する。

### 変更したファイル

| ファイル | 主な変更 |
| --- | --- |
| `web/player.html` | TCPメトリクスの個別表示、利用メトリクスの選択UI、輻輳判定、品質ダウンシフト、ログ出力 |
| `scripts/tcp_info_signal_server.py` | Linux `TCP_INFO`の取得と、推定パケットロス率を含むWebSocket通知 |
| `scripts/mock_tcp_signal_server.py` | 実機なしで表示とABR動作を確認するためのモックメトリクス生成 |
| `docs/tcp_metrics_protocol.md` | WebSocketで送受信する`tcp_metrics` JSONの仕様 |

### 起動方法

実TCP接続の情報を使う場合は、通常の`python3 -m http.server`ではなく、
TCP観測機能を持つサーバをプロジェクトルートで起動する。

```bash
python3 scripts/tcp_info_signal_server.py \
  --host 0.0.0.0 \
  --http-port 8000 \
  --ws-port 8765 \
  --serve-dir /home/l0gic/abr-pretest \
  --poll-ms 500 \
  --cc auto
```

既定の`--cc auto`では、対象HTTPソケットの`TCP_CONGESTION`から実際の方式を取得する。
`--cc cubic`と`--cc bbr`は再現試験用の明示的な上書きとして使用する。

```text
http://127.0.0.1:8000/web/player.html
```

画面の既定値では、DASH MPDとして
`http://127.0.0.1:8000/dash/test2/stream.mpd`、TCP通知として
`ws://127.0.0.1:8765`が使用される。

実TCP情報を使わずUIだけを確認する場合は、別ターミナルでモックサーバを起動できる。

```bash
python3 scripts/mock_tcp_signal_server.py \
  --host 0.0.0.0 \
  --port 8765 \
  --scenario oscillate \
  --cc cubic
```

### ブラウザに表示されるTCPメトリクス

| 表示 | JSONフィールド | 単位・意味 |
| --- | --- | --- |
| TCP Age | ブラウザ受信時刻から算出 | 最新メトリクスを受信してからの経過時間（ms） |
| RTT | `rtt_us` | Linux TCPが保持する平滑化RTT。画面ではmsへ変換 |
| RTTx | `rtt_us / rtt_min_us` | 最小RTTに対する現在RTTの倍率。キュー増加の兆候 |
| CWND | `cwnd_packets`, `cwnd_bytes` | TCP送信側の輻輳ウィンドウ。パケット数とKiBで表示 |
| Packet Loss | `packet_loss_rate` | 直近サンプルの再送率から求めた推定パケットロス率 |
| RETX | `retransmissions_delta` | 前回サンプルから増えた再送パケット数 |

`Packet Loss`は物理リンク上の損失を直接測定した値ではない。
`TCP_INFO`の累積再送数の増分を、同期間の送信パケット数で割った再送ベースの推定値である。
そのため、実験結果では「推定パケットロス率」または「再送率」として扱う。

TCP Signal Max Ageの既定値は1500 msである。これを超えた情報は`stale`とし、
画面には古いことを表示するが、ABR判断には使わない。通知がない場合も通常のABRへ
自動的にフォールバックする。

### ABR判断に使うメトリクスの選択

画面の「TCP signals used by ABR guardrail」で、次の信号を個別に選択できる。

| 選択項目 | 既定値 | ABRで評価する情報 |
| --- | --- | --- |
| RTT / RTTx | ON | RTT膨張率。BBRではdelivery rateも補助的に確認 |
| CWND | OFF | セッション中の最大CWNDに対する低下と、ウィンドウ使用率 |
| Packet loss / RETX | ON | 推定損失率と直近の再送増分 |

チェックを外したメトリクスも画面には表示されるが、輻輳判定には使われない。
`TCP-Aware Mode`を`Off`にすると、WebSocket受信と表示は継続したまま、
すべてのTCP情報をABR判断から除外する。この「Observation only」により、
同じ画面で通常ABRとTCP-aware ABRを比較できる。

### TCPメトリクスによる輻輳判定

チェックされたメトリクスについて、以下のいずれかを満たすと輻輳候補とする。

#### RTT / RTTx

共通条件として、最小RTTが1 ms以上、RTTの絶対増加が5 ms以上、かつ3サンプル連続で
成立した場合だけ判定する。

* CUBIC：上記に加えて`RTTx > 1.5`
* BBR：上記に加えて`RTTx > 1.4`かつ`delivery_rate_bps < 現在の動画ビットレート × 1.15`

BBRではRTTが周期的に変動する可能性があるため、RTT膨張だけでは品質を下げず、
配送レートにも余裕がない場合に限ってRTT由来の輻輳と判断する。
`app_limited`なサンプルは配送レート比較から除外する。

#### Packet loss / RETX

次のどちらかを満たすと輻輳と判断する。

* `retransmissions_delta > 0`
* `packet_loss_rate > 0.02`（2%超）

#### CWND

次の両方を満たすと輻輳と判断する。

* 現在のCWNDが、その再生セッションで観測した最大CWNDの60%以下
* 未ACKパケット数（`packets_out`）が現在CWNDの80%以上

CWNDが小さいだけでは、通信量が少ない正常状態と区別できない。
そのため、CWNDの低下とウィンドウの高い使用率を組み合わせて誤検出を抑えている。
また、BBRではCWND単独の意味がCUBICより弱いため、CWND利用は既定でOFFとしている。

複数の項目をONにした場合はOR条件であり、選択された信号のどれか1つが
条件を満たすと輻輳候補になる。

### ABRが変更される機序

品質変更までの処理は次の順序で行われる。

1. dash.jsのThroughputまたはBOLAが通常どおり品質を決める。
2. 動画セグメントのダウンロード完了時に、最新のTCPメトリクスを取得する。
3. 情報が1500 ms以内であることと、選択されたTCP信号の閾値を確認する。
4. 輻輳と判定しても、バッファが8秒より多く、再生停止がまだない場合は
   `Watching`として品質を維持する。
5. 前回のTCP Guardrail動作から6000 ms未満の場合は`Cooldown`として連続変更を防ぐ。
6. 上記の抑制条件がなく、最低品質でもない場合、現在品質を1段階下げる。

同一の`connection_id`と`timestamp_ms`を持つTCPサンプルは、品質変更へ一度しか使用しない。

```text
nextQuality = max(0, currentQuality - 1)
```

品質変更にはdash.jsの
`setRepresentationForTypeByIndex("video", nextQuality)`を使用する。
TCP情報から特定のビットレートを直接計算したり、一度に複数段階下げたりはしない。
信号が欠損・期限切れの場合や、TCP-Aware ModeがOffの場合は品質を強制せず、
Throughput/BOLAの判断をそのまま使用する。

### 画面表示とログ

`TCP Signal`カードには、選択中の信号に基づく`Healthy`または
`Congested: RTT`、`Congested: LOSS/RETX`、`Congested: CWND`などが表示される。
`Guardrail`カードには次の状態が表示される。

| 状態 | 意味 |
| --- | --- |
| `Observation only` | TCP情報は表示のみでABRには不使用 |
| `Healthy` | 選択したTCP信号に輻輳兆候なし |
| `Congestion detected` | 輻輳条件を検出 |
| `Watching` | バッファに余裕があるため品質を維持 |
| `Cooldown` | 連続した品質低下を抑制中 |
| `Downshift to Qn` | 品質インデックス`n`へ1段階低下 |
| `At lowest quality` | すでに最低品質 |
| `No fresh TCP signal` | TCP情報がない、または期限切れ |

Start時のログには`tcpSignalsUsed`として選択状態が保存される。
各`TCP_SIGNAL_UPDATE`、品質変更、セグメント受信、heartbeatログにも
その時点のTCPスナップショットが含まれる。Guardrailによる変更は
`TCP_GUARDRAIL_APPLIED`イベントとして、変更前後の品質、バッファ量、
判断時のTCPメトリクスとともに記録される。

---

## 🌐 ネットワーク制御


```bash
sudo tc qdisc replace dev enp2s0 root netem \
  rate 3mbit \
  delay 50ms 10ms \
  loss 5%
```

```
chmod +x toggle_bw.sh
./toggle_bw.sh
```

---

## ⚙️ 輻輳制御切替

### CUBIC

```bash
sudo sysctl -w net.ipv4.tcp_congestion_control=cubic
```

### BBR

```bash
sudo sysctl -w net.core.default_qdisc=fq
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr
```


---

## 🧪 実験条件

| ABR        | CC    |
| ---------- | ----- |
| Throughput | CUBIC |
| BOLA       | CUBIC |
| Throughput | BBR   |
| BOLA       | BBR   |

---

## 📊 評価指標

* バッファレベル
* 再生停止イベント
* 品質切替回数
* 再生安定性

---

## 📈 予備実験結果（概要）


## 🧠 考察

---

## 開発時の自動テスト

```bash
python3 -m unittest discover -s tests -v
```

## Dockerでの基本動作確認

Docker版はLinux上でTCP_INFO collector、WebSocket、静的プレイヤをまとめて確認するための
再現環境である。eBPF版の検証では、別途BPF権限とホストカーネル機能が必要になる。

```bash
docker compose build
docker compose up -d
docker compose ps
curl http://127.0.0.1:8000/web/player.html
docker compose down
```

## eBPF collectorのビルドとsmoke test

eBPFビルダーは実行環境の`arm64`または`x86_64`を自動判定する。smoke testは一時的に
sockopsプログラムをコンテナ自身のcgroupへattachし、TCP通信中にmap更新とJSON変換を
確認した後、programとmapを自動削除する。

```bash
docker build -f Dockerfile.ebpf -t gp-ebpf-builder .
docker run --rm gp-ebpf-builder
docker run --rm --privileged --cgroupns=host \
  -v /sys/fs/bpf:/sys/fs/bpf \
  gp-ebpf-builder sh /src/ebpf/smoke_test.sh
```

既にpinされたmapをJSON Linesとして確認する場合：

```bash
python3 scripts/ebpf_map_reader.py \
  --map /sys/fs/bpf/tcp_metrics \
  --cc cubic \
  --interval-ms 500
```

### eBPF mapをWebSocket APIへ接続

sockopsプログラムをattachしてmapをpinした後、同じHTTP/WebSocketサーバを
eBPF collectorモードで起動する。eBPF map自体からCC名は取得しないため、実験条件を
`--cc`で明示する。

```bash
python3 scripts/tcp_info_signal_server.py \
  --collector ebpf \
  --ebpf-map /sys/fs/bpf/tcp_metrics \
  --cc cubic \
  --serve-dir .
```

プレイヤのTCP Guardrailはdash.js 5.1.1の`qualitySwitchRules`として登録される。
通常時は画面で選んだThroughputまたはBOLAが判断し、確認済みのTCP輻輳時だけ
custom ruleが選択可能な最大Representationを1段下げる。

## tc/netem反復実験

標準プロファイルは`experiments/netem_profiles.json`にある。まず実行予定を確認する。

```bash
python3 scripts/run_netem_experiments.py \
  --interface eth0 \
  --command './your-playback-probe.sh' \
  --repetitions 5 \
  --dry-run
```

Docker内で実行する場合は、ホストの通信を変更せず専用コンテナの`eth0`だけを整形できる。

```bash
docker compose -f compose.experiment.yaml build
docker compose -f compose.experiment.yaml run --rm tcp-metrics-experiment \
  python scripts/run_netem_experiments.py \
  --interface eth0 \
  --command './your-playback-probe.sh' \
  --repetitions 5
```

各試行は`results/netem/<profile>-rNN/`へ標準出力、標準エラー、条件、終了コード、
所要時間を保存する。中断、失敗、正常終了のいずれでもnetem qdiscを解除する。
