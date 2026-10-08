# weather-forecast

日本国内の天気予報の質問に、気象庁の最新の公式予報から答える Claude Code スキルです。
「明日の札幌の天気は？」「週末の京都は雨？」のように普通に聞くか、
`/weather-forecast <地名>` で呼び出します。

答える内容:

- **今日〜明後日** — 天気、6 時間ごとの降水確率、朝の最低気温と日中の最高気温、風（沿岸は波も）
- **週間予報** — 天気、降水確率、信頼度（A/B/C）、気温の幅
- **天気概況** — 気象台が書いた天気の解説文

答えには必ず地域名と発表時刻を添え、最後に気象庁の利用規約が求める出典を記載します。
API キーやアカウントは要りません。

対象外: 国外の地名、警報・注意報（聞かれたら気象庁の警報ページを案内します）、
現在の観測値、雨雲レーダー。

## インストール

[Releases](https://github.com/nlink-jp/weather-forecast/releases) から
`weather-forecast-vX.Y.Z.zip` をダウンロードし、次のいずれかで登録します。

- **Claude Desktop** — スキルの設定（カスタマイズ → スキル）から zip を追加します。
  スキルの保存場所が変わっても壊れないので、こちらを推奨します。
- **Claude Code** — `unzip weather-forecast-vX.Y.Z.zip -d ~/.claude/skills/`。
  プロジェクト単位で入れる場合はそのプロジェクトの `.claude/skills/` へ。

チェックアウトから入れる場合:

```bash
make install
```

リリース用の zip を作り、その zip を展開して入れます。`make install DEST=/path/to/skills`
で別の場所へ、`make uninstall` で削除します。

必要なもの: `python3`（3.9 以上、標準ライブラリのみ）と、スキルを動かす場所から
`www.jma.go.jp` へ接続できること。Claude Code（デスクトップアプリの Code タブと CLI）は
これを満たします。claude.ai のチャットの実行環境は外部への接続先が制限されており、
気象庁には届かない見込みです。

## 使い方

```
/weather-forecast 札幌
/weather-forecast 那覇 week
明日の京都は雨が降りますか？
週末の伊豆大島の天気を教えて
```

地名が複数の場所に当たるとき（「府中」は東京都と広島県にあります）は、どちらかを聞き返します。

同梱のスクリプトは直接実行もでき、JSON を出力します:

```bash
python3 ~/.claude/skills/weather-forecast/scripts/jma_forecast.py resolve 札幌
python3 ~/.claude/skills/weather-forecast/scripts/jma_forecast.py forecast --office 016000 --area 016010
```

## 開発

| コマンド | 内容 |
|---------|------|
| `make check`（= `make test`） | 構造検証とスクリプトの動作テスト（オフライン） |
| `make install` | zip を作り `~/.claude/skills/weather-forecast` に展開 |
| `make package` | `dist/weather-forecast-vX.Y.Z.zip` を作成（zip のルート = スキルのフォルダ） |
| `make check-upstream` | スクリプトの読み方が今の気象庁のデータに合っているかを確認（オンライン） |
| `make sync-telops` | 同梱の天気名の表を気象庁の予報ページと突き合わせる（オンライン） |

## ドキュメント

- [ADR-0001: 気象庁の予報を決定的スクリプトで整形する](docs/ja/adr/0001-jma-forecast-skill.ja.md)
- [English documentation](README.md)

## 出典

予報データ: [気象庁](https://www.jma.go.jp/bosai/forecast/)。気象庁ホームページの利用規約
（公共データ利用規約 第1.0版）に基づいて利用しています。スキルは内容を整形・要約しており、
答えにその旨を記載します。

## ライセンス

MIT
