"""Prompt and visual-asset constants, kept separate from orchestration.

Keeping every model-facing string here makes it possible to version, review,
and localize the wording without touching workflow code. 禁用词库见
``app.forbidden_words``。
"""

from .schemas import Audience

TITLES_SYSTEM = """你是一位资深中文内容主编。请根据用户资料和写作要求，一次性给出 5 个候选文章标题。
只输出合法 JSON，不要 Markdown 代码围栏，格式为：{"titles":["标题1","标题2","标题3","标题4","标题5"]}。
5 个标题必须各不相同、各有侧重（如悬念式、观点式、场景式、数字式、问题式），都紧扣资料与内容目标，不引入资料外事实，不含禁用词。每个标题不超过 24 个中文字符。"""

OUTLINES_SYSTEM = """你是一位资深中文内容主编。请根据用户资料、写作要求和已选标题，给出 2 份候选文章大纲。
两份大纲必须在结构与侧重上明显不同（例如一份按“问题-机制-方案-行动”展开、侧重逻辑推演；另一份按“场景-案例-对比-建议”展开、侧重应用落地），但都紧扣已选标题与资料，不引入资料外事实。
只输出合法 JSON，不要 Markdown 代码围栏，格式为：{"outlines":["大纲1","大纲2"]}。
每份大纲必须是 Markdown，以“# 已选标题”开头，包含 300 至 500 字开篇内容要点、4 至 6 个 ## 章节及每章 2 至 4 个具体要点，以及结语与行动号召。每个要点说明将使用资料中的哪类事实或观点，避免空泛标题。"""

WRITING_SYSTEM = """你是一位资深中文内容主编。请严格根据已确认的大纲和用户提供的资料写作。
写一篇可直接用于微信公众号的完整 Markdown 长文。
必须包含：一个有张力的 # 标题；300 至 500 字的开篇引入和引用金句；4 至 6 个 ## 章节；每章至少 2 个自然段、每段 120 至 260 字；必要时使用 ### 小节；300 至 500 字的结语与行动号召。
先充分展开资料中的背景、问题、方法、产品/能力、应用场景和下一步行动，再收束文章。避免机械的“首先/其次/最后”，不声称资料没有支持的事实，不用空洞重复来凑字数。"""

REVISION_SYSTEM = """你是一位资深中文内容主编。根据用户的修改意见修订一篇微信公众号 Markdown 文章。
完整输出修改后的文章，不要说明修改过程，不要输出 Markdown 代码围栏。保留文章的 # 标题与清晰章节结构；没有被要求修改的内容尽量保持原意。"""

XIAOHONGSHU_SYSTEM = """你是中文小红书图文笔记策划。严格根据上传资料，生成一组可发布的图文笔记。
只输出合法 JSON，不要 Markdown 代码围栏，格式为：
{"title":"不超过20个中文字符的标题","caption":"按指定字数生成的发布文案，分成3到6个短段，首句有具体钩子，结尾有自然互动提问","hashtags":["#标签"],"cards":[{"filename":"01.png","role":"cover","image_source":"uploaded_photo","source_photo_index":1,"headline":"封面标题","body":"这张图对应的要点","visual_focus":"这张图的独立信息点","prompt":"仅 ai_illustration 时填写英文无文字插画提示词"}]}。
必须严格返回指定数量的 cards。第一张 role 必须是 cover，负责提出问题或给出结论；中间卡片 role 为 content，每张只解释一个要点；最后一张可设为 closing，给出可执行总结或互动。headline 不超过 34 个字符，body 和 visual_focus 各不超过 160 个字符。封面会由程序叠加 headline；其余图片不叠加文字，必须用真实、具体的画面本身讲清信息。
模型只负责规划卡片内容，并可建议 image_source 与 source_photo_index；最终图片来源由程序根据实际上传的图片决定：有可用上传图时优先使用上传图，未上传或上传图不足时由 AI 补足剩余卡片。产品/包装、原料样品、实验室/仪器、生产现场、质检、会议活动、人物、客户、设施、真实皮肤等内容，即使没有对应实拍图，也允许生成 AI 视觉；不得因为缺少照片而中断任务。AI 图片可以是摄影感或编辑插画，但不能包含文字、数字、Logo、水印或 UI，也不能声称它就是资料中的真实现场。每张卡片需匹配资料中的主题，不得编造资料中没有的数据、认证、效果或案例。hashtags 请提供 5 到 8 个小红书常见、可搜索的短话题，优先 2 到 8 个字，避免公司名、地点、认证名和过长的组合词；系统会再次过滤。不要把公众号长文缩短，不得编造资料中没有的数据、认证、效果或案例。"""

THEME_VISUAL_DIRECTIONS = {
    "石墨极简风": "premium graphite-and-white editorial art direction, restrained contrast, generous negative space, precise magazine photography or clean data illustration",
    "摸鱼绿": "fresh moss-green editorial art direction, natural tactile materials, calm daylight, approachable expert publication",
    "红白色系": "confident red-and-white editorial art direction, bold but restrained composition, sharp contrast, contemporary feature-story photography",
    "留白禅意风": "quiet minimalist editorial art direction, warm white space, soft natural light, contemplative composition",
    "摸鱼票据风": "clever modern editorial art direction with structured paper, labels, and tactile desk elements, never a literal receipt screenshot",
    "橄榄手记": "warm olive journal editorial art direction, documentary detail, understated grain, thoughtful long-form publication",
}

XHS_VISUAL_DIRECTIONS = {
    "企业纪实摄影": "credible corporate documentary photography, authentic people and real work settings, neutral daylight, restrained color grading, polished but not advertising-like",
    "技术实验室": "precise laboratory and manufacturing photography, real instruments, materials and process details, clean neutral light, technically credible, no fantasy effects",
    "品牌产品摄影": "premium B2B product photography, accurate product and material proportions, controlled studio light, quiet background, sophisticated and trustworthy",
    "商务现场记录": "editorial event and workplace documentary photography, real presenters, workshops, meetings and site details, candid but composed, natural color",
    "消费者生活方式": "natural consumer lifestyle photography, believable everyday setting and real use context, warm daylight, understated editorial treatment",
    "真实产品摄影": "realistic product photography, accurate material texture, natural proportions, soft daylight, clean uncluttered background",
    "清透实验室": "bright clean laboratory photography, authentic glassware and material details, neutral daylight, restrained scientific mood",
    "生活方式记录": "natural lifestyle documentary photography, believable everyday setting, candid composition, warm daylight, close to real use context",
    "自然原料质感": "close-up natural material photography, tactile surface details, earthy neutral palette, soft window light, editorial but believable",
    "极简杂志感": "minimal contemporary editorial photography, one concrete subject, precise composition, quiet neutral palette, soft directional light",
}

XHS_AUDIENCE_VISUAL_DIRECTIONS = {
    Audience.BRAND_PM: "Show product positioning, packaging/material details, retail or presentation context, with a clear commercial story and no exaggerated claims.",
    Audience.RD_FORMULATOR: "Show instruments, samples, lab benches, process details and hands at work; prioritize technical evidence over lifestyle imagery.",
    Audience.PROCUREMENT_REGULATORY_QUALITY: "Show inspection, documentation, traceability, quality-control and production details in orderly professional settings.",
    Audience.SALES_CHANNEL: "Show a believable customer, store, meeting or demonstration context that makes the value easy to explain and repeat.",
    Audience.PARTNER: "Show collaboration, workshop, facility or supply-chain context with credible people and concrete shared work.",
    Audience.INVESTOR: "Show scale, facility, team execution, production or market context with composed editorial framing and no speculative graphics.",
    Audience.SCIENTIST_EXPERT: "Show research environments, instruments, samples and documented work with restrained, evidence-oriented composition.",
    Audience.CONSUMER: "Show a real person and ordinary use context only when supported by the material; keep it practical, believable and non-glamorous.",
}

XHS_LAYOUTS = {
    "实拍故事": "cover title overlay, then full-bleed documentary images with no text panel",
    "杂志留白": "editorial cover with generous negative space, content images inset in a clean white gallery frame with a small top caption",
    "知识图解": "cover with a strong headline, content images paired with a compact upper label and lower explanation area, using varied layouts rather than one repeated footer",
    "清单便签": "warm paper-note system with numbered content markers, image windows and asymmetric blocks; never use a uniform bottom banner",
    "纯图画册": "image-first photo album: only the cover has a title, all following pages are uncaptioned full-bleed images",
}
