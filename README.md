

# 📄 README.md

## 概要

本プロジェクトでは、
**動画ストリーミングにおける輻輳制御（CC）とABR方式の組合せがQoEに与える影響**を評価する。

特に、モバイル環境を想定したネットワーク変動下において、

* Throughput-based ABR
* BOLA（Buffer-based ABR）

と、

* CUBIC
* BBR

の組合せによる再生挙動の違いを比較する。

---

## 🎯 目的

* ABR方式の違いによるQoE差を確認
* 輻輳制御アルゴリズムの影響を評価
* 両者の**相互作用（cross-layer effect）**を明らかにする

---

## 🧪 実験構成

### システム構成

* 配信サーバ：nginx（HTTP配信）
* クライアント：dash.js（ブラウザ）
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

