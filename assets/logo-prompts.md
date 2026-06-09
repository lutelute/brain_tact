# brain_tact ロゴ生成プロンプト集

手描きSVGではなく**画像生成AI**で作る。タクト(指揮棒=複数セッションを統率)が主コンセプト。

## コンセプト

> 指揮者(conductor)が、散らかった複数の Claude Code セッションを **タクト(指揮棒)** で統率し、片付ける。
> brain = 判断する頭脳 / tact = 統率する指揮棒。

## 推奨サービス

| サービス | 強み | URL |
|---|---|---|
| **Ideogram** | ロゴ・テキスト入りに最強・無料枠あり(最初の一手に推奨) | ideogram.ai |
| **DALL·E 3** | ChatGPT/Copilotから手軽 | chatgpt.com |
| **Midjourney** | 最高品質(有料・Discord) | midjourney.com |

生成は **正方形(1:1)・アイコン用途・背景透過 or 単色** を指定。テキストなしで図案だけ作り、READMEバナーのテキストは後で別途合成すると綺麗。

---

## プロンプト(タクト系・コピペ用・英語)

### T1 — 指揮棒 × ターミナル(本命)
```
App icon for a developer tool "brain_tact". A sleek conductor's baton held at a
dynamic diagonal, its tip leaving a luminous motion trail that conducts three small
glowing terminal windows arranged like an orchestra below. Minimalist flat vector,
rounded-square icon, deep charcoal background, emerald-green and warm-gold accents,
soft glow, premium SaaS aesthetic like Linear and Vercel, crisp geometry, no text,
centered, high contrast.
```

### T2 — 指揮棒 × 波(音=セッション)
```
Minimal logo mark for "brain_tact". An elegant conductor's baton sweeping across
three layered sound waves that resolve into clean horizontal lines, symbolizing many
voices brought into harmony. Vector, monoline, gold baton over deep navy, subtle cyan
waves, geometric, balanced negative space, modern tech branding, flat, no text.
```

### T3 — 指揮棒 × 脳(brain+tact 融合)
```
Logo for "brain_tact": a stylized human brain whose neural lines extend into a
conductor's baton, fusing intellect and orchestration. Single continuous line-art
style, gradient from violet to cyan, dark background, minimalist, premium, vector
app icon, rounded square, no text, symmetrical, elegant.
```

### T4 — 指揮者のジェスチャー(抽象)
```
Abstract minimalist mark representing orchestration and control. A confident upward
baton stroke with a small bright node at the grip, three subtle parallel elements
falling into alignment beneath it. Flat geometric vector, emerald and gold on near-black,
Swiss design influence, app icon, balanced, no text, high-end developer-tool branding.
```

---

## 生成後のリファイン手順

1. 上記で4枚ほど生成 → 良いものを1つ選ぶ
2. 背景透過 or 単色に整える(remove.bg / Ideogramの背景指定)
3. このセッションに **画像を貼ってください**。こちらで:
   - `assets/logo.png`(512px 正方形)
   - `assets/favicon.png`(32px)
   - `assets/banner.png`(README用・横長、テキスト "brain_tact" + タグライン合成)
   に書き出し、README 冒頭とダッシュボードに組み込みます

## バナー用タグライン候補

- 散らかった Claude Code セッションを、見て・束ねて・片付ける
- the conductor for your terminal sessions
- 20-30個のセッションを統率する定時巡回 brain
