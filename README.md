**日本語** | [繁體中文](README.zh-TW.md)

# Spotify Mini

デスクトップ向けミニプレイヤー。**Spotify API 不要**。Windows のメディア統合トランスポート
コントロール（SMTC）経由で Spotify デスクトップ版を読み取り・操作します。ブラウザなど他の
メディアソースにも対応。カバーアートからの自動配色、フル自前描画 UI、時間ベースのアニメーション
により、高 FPS と低 CPU 使用率を両立します。

<p align="center">
  <img src="assets/player.png" width="640" alt="プレイヤー画面">
</p>

## 特徴

- 再生中の曲・カバー・進捗を読み取り、前/次の曲・再生/一時停止・シャッフル・リピート・音量を操作。
- ソースは Spotify / ブラウザ / 再生中セッションの自動選択 から選べます。
- テーマ：カバー自動抽出 / すりガラス透過 / カスタムグラデーション / 単色スウォッチ / 2色グラデーション。
- 豊富なビジュアルエフェクト（カバービジュアライザー、波形シークバー、降水エフェクトなど）と FPS 調整（24–144）。
- 拡大率・角丸・フォント・アニメーション強度をリアルタイム切り替え。多言語対応（日本語 / 繁体字中国語 / 英語）。
- タスクトレイ常駐、単一インスタンス、編集モードによる自由レイアウト。

<p align="center">
  <img src="assets/settings.png" width="720" alt="設定画面">
</p>

## 動作環境

- Windows 10 / 11
- Spotify デスクトップ版のインストール（再生に必要。DRM はクライアント側のため、Spotify を起動せずに再生はできません）
- ソースから実行する場合は Python 3.10+

## ソースから実行（uv）

```bash
# uv のインストール（未導入の場合）
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# コードを取得
git clone https://github.com/lancealan0121/spotify_mini.git
cd spotify_mini

# 仮想環境を作成して依存関係をインストール
uv venv
uv pip install -r requirements.txt

# 実行
uv run python main.py
```

`run.bat` でも起動できます（`pythonw` でコンソールなし起動）。

## 単一実行ファイルへのビルド

```bash
build.bat
```

PyInstaller で `dist\MiniSP_<日付>.exe` を生成します（初回は PyInstaller を自動インストール）。

## ライセンス

本プロジェクトは [MIT License](LICENSE) で公開されています。

Spotify は Spotify AB の商標です。本プロジェクトは Spotify AB と提携・承認関係にありません。
`spt.png` の商標素材はソース表示の目的でのみ使用しています。
