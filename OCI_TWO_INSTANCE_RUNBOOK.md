# OCI 2インスタンス分離ランブック（Web / Bot）

この手順は、以下の2台分離を最短で実施するためのものです。

- `VM-WEB`: 九州商事サイト公開専用（HTTPS公開）
- `VM-BOT`: 取引Bot/ダッシュボード専用（原則非公開）

---

## 1. 事前準備

必要情報:

- `WEB_VM_IP` : Web用VMのPublic IP
- `BOT_VM_IP` : Bot用VMのPublic IP
- `SSH_KEY` : OCI秘密鍵パス
- `WEB_DOMAIN` : Web公開ドメイン（例: `ks.example.com`）

例:

```bash
export WEB_VM_IP="1.2.3.4"
export BOT_VM_IP="5.6.7.8"
export SSH_KEY="$HOME/.ssh/oci_vm_key.pem"
export WEB_DOMAIN="ks.example.com"
```

---

## 2. OCIネットワーク設定（先に実施）

### VM-WEB 側

- Ingress許可: `22/tcp`, `80/tcp`, `443/tcp`
- DNS Aレコード: `${WEB_DOMAIN} -> ${WEB_VM_IP}`

### VM-BOT 側

- Ingress許可: `22/tcp` のみ推奨
- `8501/tcp` は閉じる（必要時のみIP制限で一時開放）

---

## 3. VM-WEB 構築（九州商事サイト）

### 3.1 コード配布

```bash
scp -i "$SSH_KEY" -r ~/trading_bot/trading_bot ubuntu@"$WEB_VM_IP":~/
```

### 3.2 HTTPS公開セットアップ（VM上）

```bash
ssh -i "$SSH_KEY" ubuntu@"$WEB_VM_IP"
cd ~/trading_bot/trading_bot/MAIN/kyushu_shoji_site
chmod +x ./oracle_vm_https_setup.sh
./oracle_vm_https_setup.sh --domain "$WEB_DOMAIN" --app-user ubuntu
```

### 3.3 稼働確認（VM上）

```bash
sudo systemctl status kyushu-shoji-site --no-pager -l
sudo systemctl status caddy --no-pager -l
curl -fsS http://127.0.0.1:8080/health
```

ブラウザ確認:

```text
https://<WEB_DOMAIN>
```

---

## 4. VM-BOT 構築（取引Bot/ダッシュボード）

### 4.1 配布 + セットアップ（ローカルから実行）

```bash
cd ~/trading_bot/trading_bot
./MAIN/tools/deploy_to_ubuntu_vm.sh --host "$BOT_VM_IP" --user ubuntu --key "$SSH_KEY" --with-secrets
```

### 4.2 VM上確認

```bash
ssh -i "$SSH_KEY" ubuntu@"$BOT_VM_IP"
cd ~/trading_bot/trading_bot/MAIN
./tools/cloud_systemd_healthcheck.sh --run-preflight
```

---

## 5. 分離後の運用ルール

1. 九州商事サイト更新は `VM-WEB` のみで実施  
2. Bot/ダッシュボード更新は `VM-BOT` のみで実施  
3. APIキーや取引秘密情報は `VM-BOT` の `/etc/ouroboros/secrets.env` のみ管理  
4. `VM-WEB` に取引系キーを置かない  
5. `VM-BOT` は原則 22/tcp のみ公開し、ダッシュボード公開は必要時に限定する

---

## 6. トラブル時の確認コマンド

### VM-WEB

```bash
sudo journalctl -u kyushu-shoji-site -n 120 --no-pager
sudo journalctl -u caddy -n 120 --no-pager
curl -I "https://${WEB_DOMAIN}"
```

### VM-BOT

```bash
sudo systemctl status ouroboros-bot.service --no-pager -l
sudo systemctl status ouroboros-dashboard.service --no-pager -l
sudo journalctl -u ouroboros-bot.service -n 120 --no-pager
```

