from .schemas import Audience


AUDIENCE_STRATEGIES: dict[Audience, dict[str, str]] = {
    Audience.BRAND_PM: {"tone": "商业化、清晰、有判断", "focus": "定位、产品价值、市场机会", "structure": "问题-机会-方案-行动"},
    Audience.RD_FORMULATOR: {"tone": "严谨、专业、克制", "focus": "技术原理、参数、工艺和使用边界", "structure": "问题-机制-方案-实践"},
    Audience.PROCUREMENT_REGULATORY_QUALITY: {"tone": "稳健、清晰、风险敏感", "focus": "质量管理、供应稳定性、认证与流程", "structure": "关注点-控制方式-协作建议"},
    Audience.SALES_CHANNEL: {"tone": "直接、有场景感、易转述", "focus": "客户痛点、卖点、异议处理和落地动作", "structure": "客户问题-价值点-场景-行动"},
    Audience.PARTNER: {"tone": "开放、共创、务实", "focus": "协同价值、资源互补和合作机制", "structure": "共同机会-能力互补-合作路径"},
    Audience.INVESTOR: {"tone": "理性、简洁、结果导向", "focus": "市场趋势、增长逻辑、差异化和长期价值", "structure": "趋势-机会-壁垒-下一步"},
    Audience.SCIENTIST_EXPERT: {"tone": "学术化、精准、保留边界", "focus": "研究问题、方法逻辑和讨论价值", "structure": "问题-观点-方法-讨论"},
    Audience.CONSUMER: {"tone": "亲切、易懂、避免术语堆砌", "focus": "真实场景、使用体验和简单行动", "structure": "场景-困扰-解决方式-行动"},
}

