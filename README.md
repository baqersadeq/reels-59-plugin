# reels-59

مهارة لـ Claude Code تخطّط لمونتاج ريلز عمودية مدتها 59 ثانية في Adobe Premiere Pro، تُبنى قطعاتها على إيقاع خلفية صوتية (قصيدة، آهات، موسيقى)، مع فحص جودة اللقطات، وتصحيح لوني أولي، وكابشن، وصبغة لونية نهائية.

A Claude Code skill that plans a 59-second vertical (1080×1920) reel in Adobe Premiere Pro, cutting to an audio bed such as a poem, vocals or music. It covers sequence setup, cut timing, shot quality checks, colour correction, captions and a final grade. Without a Premiere Pro MCP server it can build and render the reel with HyperFrames (`npx skills add heygen-com/hyperframes`, needs Node.js 22+ and FFmpeg), or output a written edit plan.

## Install

Requires Git.

```
/plugin marketplace add baqersadeq/reels-59-plugin
/plugin install reels-59@baqer-skills
```

## Use

Type `/reels-59`, or ask naturally, e.g. «سوّ لي ريلز على هذه القصيدة».
