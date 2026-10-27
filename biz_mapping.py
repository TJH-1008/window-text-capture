"""业态对照表的发现、读取与匹配（仅用标准库）。

1.5.0 起，业态对照表不再写死"餐饮/零售/亲子儿童/休闲娱乐"白名单：
表里出现什么标准业态就以什么为准，表里怎么改都不用改代码。

支持两种文件：
- CSV：UTF-8(BOM)/GB18030/UTF-16，逗号/分号/制表符分隔，表头可带空行或标题行。
- XLSX：任意工作表，只要表头含"细分业态""标准业态"即可；不需要装 Excel 或 openpyxl。

匹配优先级：表内精确 → 表内"别名"列 → 内置别名 → 内置关键词 → 其他/待复核。
每一步都可追溯，未匹配的不猜，统一进"业态待补清单"。
"""

import csv
import hashlib
import io
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

TABLE_KEYS = ("细分业态", "标准业态")
ALIAS_KEY = "别名"
FALLBACK_GROUP = "其他/待复核"
# 平台把这些也放在"分类"里，但它们是场地设施而不是品牌业态，不做业态归并。
NON_BRAND = frozenset({"停车场", "更多购物场所", "充电站/桩", "智能按摩空间", "智能自助设施"})
TABLE_SUFFIXES = {".csv", ".txt", ".xlsx", ".xlsm"}
TABLE_MARK = "业态"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# 表头同义词：写表的人常把列名改成自己的说法。
HEADER_SYNONYMS = {
    "category": ("细分业态", "细分分类", "细分行业", "业态细分", "原业态", "平台业态", "业态名称"),
    "group": ("标准业态", "标准分类", "标准业态名称", "四大业态", "四大业态一级", "一级业态", "大类", "归类"),
    "alias": ("别名", "同义词", "平台原文", "平台原始业态", "同义名称", "其他写法"),
}
# 表内没有对照表时的兜底（与 1.5.0 发行版对照表一致，四类标准业态）。
DEFAULT_ROWS = [
    ("咖啡", "餐饮"), ("小吃快餐/简餐", "餐饮"), ("烘焙甜点", "餐饮"), ("火锅", "餐饮"),
    ("川菜", "餐饮"), ("西餐", "餐饮"), ("茶饮果汁", "餐饮"), ("烧烤", "餐饮"), ("粤菜", "餐饮"),
    ("创意特色菜", "餐饮"), ("日料", "餐饮"), ("东南亚菜", "餐饮"), ("韩料", "餐饮"),
    ("江浙菜", "餐饮"), ("江西菜", "餐饮"), ("烤肉", "餐饮"), ("云南菜", "餐饮"), ("东北菜", "餐饮"),
    ("贵州菜", "餐饮"), ("湘菜", "餐饮"), ("海鲜", "餐饮"), ("京菜", "餐饮"), ("台湾菜", "餐饮"),
    ("新疆菜", "餐饮"), ("自助餐", "餐饮"), ("烤鱼", "餐饮"), ("餐酒吧/livehouse", "餐饮"),
    ("茶馆", "餐饮"), ("其他地方菜系", "餐饮"),
    ("服饰", "零售"), ("杂货礼品", "零售"), ("户外运动", "零售"), ("家居家电", "零售"),
    ("二次元", "零售"), ("珠宝首饰", "零售"), ("鞋履箱包", "零售"), ("美妆香氛", "零售"),
    ("电子数码", "零售"), ("零食", "零售"), ("内衣/家居服", "零售"), ("钟表眼镜", "零售"),
    ("汽车", "零售"), ("食材", "零售"), ("中药", "零售"), ("自行车", "零售"), ("书店", "零售"),
    ("儿童鞋服", "零售"), ("儿童用品", "零售"), ("母婴", "零售"),
    ("其他（复合业态，如服饰+餐饮）", "零售"),
    ("剧场/剧院", "娱乐"), ("展览/展馆", "娱乐"), ("VR", "娱乐"), ("密室/剧本杀", "娱乐"),
    ("KTV", "娱乐"), ("电玩游艺", "娱乐"), ("露营", "娱乐"), ("影院", "娱乐"),
    ("电竞网咖", "娱乐"), ("桌游/棋牌", "娱乐"), ("其他", "娱乐"),
    ("运动健身", "配套"), ("宠物", "配套"), ("美发", "配套"), ("摄影写真", "配套"), ("SPA", "配套"),
    ("超市/便利", "配套"), ("美容", "配套"), ("洗浴中心", "配套"), ("鲜花", "配套"),
    ("美甲美睫", "配套"), ("医疗口腔", "配套"), ("教育培训", "配套"), ("亲子服务", "配套"),
    ("按摩足疗", "配套"), ("洗衣", "配套"), ("手机维修", "配套"), ("其他", "配套"),
]

# 平台（大众点评小程序）实际出现的细分业态 → 对照表里的标准细分业态。
# 只处理"同一个东西的不同叫法"，不做跨行业猜测；实在归不了的留空进待补清单。
BUILTIN_GROUPS = {
    "餐饮": {
        "咖啡": ["咖啡"],
        "茶饮果汁": ["茶饮果汁", "饮品", "酸奶鲜奶"],
        "烘焙甜点": ["面包蛋糕", "面包蛋糕甜品", "甜品", "冰淇淋", "豆花"],
        "小吃快餐/简餐": ["快餐简餐", "小吃快餐", "小吃", "小吃面食", "米线", "粉面馆", "饺子",
                     "馄饨|抄手|扁食", "卤味鸭脖", "炸鸡炸串", "冒菜", "粥店", "面馆", "包子",
                     "生煎/锅贴", "螺蛳粉", "肥肠粉", "花甲", "蹄花", "兔头/兔丁", "熟食熏酱", "美食城"],
        "火锅": ["火锅", "四川火锅", "重庆火锅", "潮汕牛肉火锅", "自助小火锅", "牛羊肉火锅", "鱼火锅",
               "小火锅", "菌菇火锅", "虾蟹火锅", "云南火锅", "椰子鸡火锅", "泰式火锅", "海鲜火锅",
               "蛙火锅", "羊蝎子火锅", "猪肚鸡火锅", "打边炉/港式火锅", "日式火锅", "串串香",
               "钵钵鸡", "串串自助", "美蛙自助", "火锅自助", "汤锅"],
        "川菜": ["川菜馆", "川菜", "酸菜鱼/水煮鱼", "干锅/香锅", "芋儿鸡"],
        "西餐": ["西餐", "牛排", "比萨"],
        "烧烤": ["烧烤", "烤串", "烧烤烤串", "烤翅", "烤羊腿"],
        "粤菜": ["粤菜", "粤菜馆", "广州菜", "潮汕菜", "粤式茶点", "茶餐厅", "客家菜", "顺德菜"],
        "创意特色菜": ["特色菜", "创意菜", "私房菜"],
        "日料": ["日本料理", "寿司", "日式简餐/快餐", "日式面条", "日式铁板烧", "日式自助", "铁板烧自助"],
        "东南亚菜": ["泰国菜", "东南亚菜", "印度菜", "越南菜"],
        "韩料": ["韩式料理", "韩式小吃"],
        "江浙菜": ["浙菜", "本帮菜"],
        "江西菜": ["江西菜"],
        "烤肉": ["烤肉", "烤肉自助", "韩式烤肉", "融合烤肉", "日式烧烤/烤肉", "拉美烤肉", "炙子烤肉"],
        "云南菜": ["云南菜|滇菜", "云南菜"],
        "东北菜": ["东北菜"],
        "贵州菜": ["贵州菜|黔菜", "贵州菜"],
        "湘菜": ["湘菜"],
        "海鲜": ["海鲜", "海鲜自助"],
        "京菜": ["北京菜", "京菜", "烤鸭"],
        "台湾菜": ["台湾菜"],
        "新疆菜": ["新疆菜"],
        "自助餐": ["自助餐", "比萨自助", "牛排自助", "素食自助"],
        "烤鱼": ["烤鱼"],
        "餐酒吧/livehouse": ["酒吧", "清吧", "特调酒吧", "精酿酒吧", "民谣酒馆", "小酒馆",
                        "Live House", "夜店", "餐酒吧/livehouse"],
        "茶馆": ["茶馆"],
        "其他地方菜系": ["其他地方菜系", "地方菜系", "其他中餐", "西北民间菜", "福建菜", "南洋中菜",
                   "焖锅", "肉蟹煲", "素食", "家常菜", "美食", "其他美食", "小龙虾"],
    },
    "零售": {
        "服饰": ["服装", "服饰", "服饰鞋包", "西服定制", "民族服饰/旅拍", "配饰", "婚纱/礼服", "中式礼服"],
        "鞋履箱包": ["鞋靴", "箱包"],
        "杂货礼品": ["杂货礼品", "居家日用", "办公用具", "古玩字画", "礼品"],
        "户外运动": ["运动户外"],
        "家居家电": ["家用电器", "家饰家纺", "家具家居", "成品家具", "定制家居", "全屋定制", "智能家居",
                 "厨卫洁具", "家用五金", "建材", "门窗", "更多家具家居", "中央空调/采暖"],
        "二次元": ["二次元", "潮玩综合馆"],
        "珠宝首饰": ["黄金首饰", "综合珠宝首饰", "珠宝首饰", "银饰珍珠", "钻石彩宝", "翡翠玉石"],
        "美妆香氛": ["化妆品"],
        "电子数码": ["数码产品", "手机数码回收", "数码"],
        "零食": ["零食", "栗子/干果"],
        "内衣/家居服": ["内衣"],
        "钟表眼镜": ["钟表", "眼镜店", "钟表维修"],
        "汽车": ["4S店", "汽车", "养车/用车", "维修保养", "加油站"],
        "食材": ["水果生鲜", "水果店", "生鲜", "食材", "烟酒茶叶"],
        "中药": ["药店", "中西药房", "中药", "滋补品", "食品滋补", "更多食品滋补"],
        "自行车": ["自行车/电动车", "自行车"],
        "书店": ["书店", "书店音像"],
        "儿童鞋服": ["儿童服饰"],
        "儿童用品": ["儿童用品", "玩具", "亲子购物", "其他亲子购物", "绘本馆", "积木拼搭"],
        "母婴": ["母婴", "母婴用品"],
        "其他（复合业态，如服饰+餐饮）": ["购物", "免税店", "综合经销商", "批发店", "特卖折扣", "集市"],
    },
    "娱乐": {
        "剧场/剧院": ["剧场/剧院", "演出场馆"],
        "展览/展馆": ["展览", "展览馆", "美术馆", "艺术中心/文化广场", "海洋馆", "文化艺术"],
        "VR": ["VR"],
        "密室/剧本杀": ["密室/沉浸互动剧", "剧本杀"],
        "KTV": ["量贩式KTV", "KTV", "自助KTV", "娱乐会所"],
        "电玩游艺": ["电玩城", "游戏厅", "娃娃屋", "抓娃娃机", "弹珠店", "主机游戏", "赛车"],
        "露营": ["露营", "休闲露营"],
        "影院": ["电影院", "私人影院"],
        "电竞网咖": ["网吧/电竞"],
        "桌游/棋牌": ["棋牌室", "桌面游戏", "棋艺"],
        "其他": ["休闲娱乐", "更多新奇体验", "新奇体验", "自拍/换装体验", "DIY手工坊", "团建拓展",
               "滑板轮滑", "溜冰/滑雪场馆", "冰雪运动", "攀岩馆", "射箭馆", "高尔夫场", "壁球馆",
               "主题乐园", "休闲园区", "录音棚", "更多景点/周边游", "景区设施", "演出/活动"],
    },
    "配套": {
        "运动健身": ["健身房", "瑜伽", "运动健身", "私教工作室", "游泳馆", "体育场馆", "拳击", "武术",
                 "武术格斗", "泰拳", "篮球场", "网球场", "足球场", "羽毛球馆", "乒乓球馆", "跆拳道馆",
                 "团操工作室", "舞蹈", "休闲运动"],
        "宠物": ["宠物店", "宠物医院", "宠物食品用品", "购宠", "萌宠体验", "其他宠物"],
        "美发": ["美发", "养发"],
        "摄影写真": ["快照摄影", "儿童摄影", "个性写真", "亲子摄影", "孕妇摄影", "婚纱摄影"],
        "SPA": ["SPA美体", "精油SPA", "美容/SPA", "瘦身纤体"],
        "超市/便利": ["超市便利"],
        "美容": ["皮肤管理", "美容", "纹绣", "祛痘", "彩妆造型", "脱毛", "医学美容", "产后恢复", "产后塑形", "纹身"],
        "洗浴中心": ["洗浴中心", "汗蒸馆"],
        "鲜花": ["花店", "植物花卉"],
        "美甲美睫": ["美甲", "美睫"],
        "医疗口腔": ["口腔医疗机构", "眼科诊所/门诊", "中医机构", "体检中心", "康复矫正"],
        "教育培训": ["课后辅导", "课后辅导/托管", "舞蹈培训", "美术", "音乐", "书法", "英语", "武术培训",
                 "武术拳类培训", "体适能培训", "篮球培训", "羽毛球培训", "游泳培训", "乒乓球培训",
                 "网球培训", "足球培训", "击剑培训", "棒球培训", "平衡车培训", "跆拳道培训", "机器人编程",
                 "程序设计", "科学实验", "其他科学探索", "益智教育", "国学", "考研", "留学",
                 "留学申请/咨询", "学历提升", "职业培训", "驾驶培训", "夜校", "AI智习室", "自习室",
                 "主持表演/模特", "生活服务培训", "美业形象培训", "更多教育培训", "综合早教", "水育早教",
                 "无人机培训", "其他运动培训", "乐器"],
        "亲子服务": ["儿童乐园", "其他亲子游乐", "亲子游乐", "亲子·活动", "亲子服务", "更多亲子服务",
                 "婴儿游泳", "月子中心", "保姆/月嫂/育儿嫂", "托班/托儿所", "幼儿园", "感觉统合", "宝宝宴/派对"],
        "按摩足疗": ["按摩足疗", "休闲按摩足浴", "推拿养生", "采耳头疗", "足部护理", "小儿推拿", "中医治疗/养生"],
        "洗衣": ["洗衣", "洗衣洗鞋", "洗涤护理", "修鞋擦鞋", "裁缝改衣"],
        "手机维修": ["手机维修", "电脑维修", "家电数码维修"],
        "其他": ["生活服务", "更多丽人", "社区养老", "养老服务", "房产中介", "财务服务", "法律服务",
               "咨询服务", "人才服务", "金融服务", "证券投资", "保险公司", "旅行社", "移民机构",
               "物流快递", "托运/国际货运", "文印广告", "通信营业厅", "营业网点", "ATM自助网点", "彩票",
               "活动中心", "婚礼策划", "婚礼会所", "婚礼喜品", "更多婚礼服务", "活动策划/场地布置",
               "甲醛检测治理", "装修设计", "局部装修", "开锁换锁", "整理收纳", "联合办公空间",
               "综合租赁", "3C数码/设备租赁", "回收", "售票点", "送水站", "图书馆", "其他文体中心",
               "其他兴趣生活", "奢侈品回收", "奢侈品护理", "酒店婚宴/宴会", "心理咨询/疗愈"],
    },
}

# 表里没写全时按关键词兜底；顺序从具体到宽泛，命中即止。
KEYWORD_RULES = (
    ("火锅", "火锅"), ("烤鱼", "烤鱼"), ("烧烤", "烧烤"), ("烤串", "烧烤"), ("咖啡", "咖啡"),
    ("茶饮", "茶饮果汁"), ("奶茶", "茶饮果汁"), ("果汁", "茶饮果汁"), ("冰淇淋", "烘焙甜点"),
    ("蛋糕", "烘焙甜点"), ("面包", "烘焙甜点"), ("甜品", "烘焙甜点"), ("小吃", "小吃快餐/简餐"),
    ("快餐", "小吃快餐/简餐"), ("简餐", "小吃快餐/简餐"), ("米线", "小吃快餐/简餐"),
    ("麻辣烫", "小吃快餐/简餐"), ("冒菜", "小吃快餐/简餐"),
    ("面馆", "小吃快餐/简餐"), ("粉面", "小吃快餐/简餐"), ("饺子", "小吃快餐/简餐"),
    ("粥", "小吃快餐/简餐"), ("自助", "自助餐"), ("寿司", "日料"), ("料理", "日料"),
    ("铁板烧", "日料"), ("烤肉", "烤肉"), ("川菜", "川菜"), ("湘菜", "湘菜"), ("粤菜", "粤菜"),
    ("京菜", "京菜"), ("江浙", "江浙菜"), ("东北菜", "东北菜"), ("西北", "其他地方菜系"),
    ("西餐", "西餐"), ("牛排", "西餐"), ("比萨", "西餐"), ("披萨", "西餐"), ("酒馆", "餐酒吧/livehouse"),
    ("酒吧", "餐酒吧/livehouse"), ("清吧", "餐酒吧/livehouse"), ("茶馆", "茶馆"), ("茶楼", "茶馆"),
    ("零食", "零食"), ("服装", "服饰"), ("服饰", "服饰"), ("鞋", "鞋履箱包"), ("箱包", "鞋履箱包"),
    ("珠宝", "珠宝首饰"), ("黄金", "珠宝首饰"), ("首饰", "珠宝首饰"), ("玉石", "珠宝首饰"),
    ("化妆", "美妆香氛"), ("美妆", "美妆香氛"), ("香氛", "美妆香氛"), ("数码", "电子数码"),
    ("家电", "家居家电"), ("家居", "家居家电"), ("家具", "家居家电"), ("建材", "家居家电"),
    ("眼镜", "钟表眼镜"), ("钟表", "钟表眼镜"), ("便利店", "超市/便利"), ("超市", "超市/便利"),
    ("药房", "中药"), ("药店", "中药"), ("中药", "中药"), ("书店", "书店"), ("母婴", "母婴"),
    ("月子", "亲子服务"), ("亲子", "亲子服务"), ("托班", "亲子服务"), ("幼儿园", "亲子服务"),
    ("儿童", "儿童用品"), ("玩具", "儿童用品"), ("宠物", "宠物"), ("美发", "美发"), ("理发", "美发"),
    ("美甲", "美甲美睫"), ("美睫", "美甲美睫"), ("美容", "美容"), ("皮肤管理", "美容"),
    ("SPA", "SPA"), ("摄影", "摄影写真"), ("写真", "摄影写真"), ("口腔", "医疗口腔"),
    ("诊所", "医疗口腔"), ("医疗", "医疗口腔"), ("培训", "教育培训"), ("教育", "教育培训"),
    ("辅导", "教育培训"), ("早教", "教育培训"), ("健身", "运动健身"), ("瑜伽", "运动健身"),
    ("游泳", "运动健身"), ("球馆", "运动健身"), ("球场", "运动健身"), ("舞蹈", "运动健身"),
    ("推拿", "按摩足疗"), ("足浴", "按摩足疗"), ("足疗", "按摩足疗"), ("按摩", "按摩足疗"),
    ("采耳", "按摩足疗"), ("洗衣", "洗衣"), ("洗鞋", "洗衣"), ("维修", "手机维修"), ("影院", "影院"),
    ("电影", "影院"), ("KTV", "KTV"), ("电玩", "电玩游艺"), ("游戏", "电玩游艺"), ("密室", "密室/剧本杀"),
    ("剧本", "密室/剧本杀"), ("剧场", "剧场/剧院"), ("剧院", "剧场/剧院"), ("展览", "展览/展馆"),
    ("展馆", "展览/展馆"), ("美术馆", "展览/展馆"), ("露营", "露营"), ("网吧", "电竞网咖"),
    ("电竞", "电竞网咖"), ("棋牌", "桌游/棋牌"), ("桌游", "桌游/棋牌"), ("VR", "VR"),
    ("鲜花", "鲜花"), ("花店", "鲜花"), ("珠宝", "珠宝首饰"),
)


def normalize(value):
    """统一全角/半角、空白和斜杠写法，只用于比较，不改原文。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u3000", "").replace("\xa0", "")
    text = re.sub(r"\s+", "", text)
    for mark in ("／", "、", "﹨", "\\"):
        text = text.replace(mark, "/")
    text = text.replace("｜", "|")
    text = re.sub(r"/{2,}", "/", text)
    return text.strip().lower()


def _header_key(value):
    text = normalize(value)
    text = re.sub(r"[（(].*?[)）]", "", text)
    for role, names in HEADER_SYNONYMS.items():
        if text in {normalize(name) for name in names}:
            return role
    return None


def _builtin_index():
    """(别名→标准细分业态, 标准细分业态→标准业态)"""
    alias, groups = {}, {}
    for group, targets in BUILTIN_GROUPS.items():
        for target, names in targets.items():
            groups[target] = group
            alias[normalize(target)] = target
            for name in names:
                alias.setdefault(normalize(name), target)
    return alias, groups


BUILTIN_ALIAS, BUILTIN_TARGET_GROUP = _builtin_index()


class MappingError(ValueError):
    """对照表本身不可用（找不到表头、空表等）。"""


class TableRow:
    __slots__ = ("category", "group", "aliases")

    def __init__(self, category, group, aliases=()):
        self.category, self.group, self.aliases = category, group, list(aliases)

    def __repr__(self):
        return f"TableRow({self.category!r}->{self.group!r})"


class Match:
    __slots__ = ("category", "group", "method", "note")

    def __init__(self, category, group, method, note=""):
        self.category, self.group, self.method, self.note = category, group, method, note

    @property
    def unmatched(self):
        return self.method == "未匹配"


class BusinessMapping:
    """一张业态对照表 + 匹配结果。标准业态不设白名单，表里写什么就是什么。"""

    def __init__(self, rows, source=None, mtime=None, fingerprint="", warnings=None, check_duplicates=True):
        self.rows = [row for row in rows if row.category]
        self.source = Path(source) if source else None
        self.mtime = mtime
        self.fingerprint = fingerprint
        self.warnings = list(warnings or [])
        self.groups, self.exact, self.conflicts, self.alias = [], {}, {}, {}
        self.check_duplicates = check_duplicates
        self._build()

    def _build(self):
        for row in self.rows:
            key = normalize(row.category)
            if key in self.exact and normalize(self.exact[key][1]) != normalize(row.group):
                self.conflicts.setdefault(key, {self.exact[key][1]}).add(row.group)
                if self.check_duplicates:
                    self.warnings.append(
                        f"对照表“{row.category}”同时对应 {'、'.join(sorted(self.conflicts[key]))}，"
                        f"该细分业态无法唯一归属，按{FALLBACK_GROUP}输出")
            else:
                self.exact[key] = (row.category, row.group)
            if row.group not in self.groups:
                self.groups.append(row.group)
            for name in row.aliases:
                name_key = normalize(name)
                if name_key and name_key not in self.exact:
                    self.alias.setdefault(name_key, (row.category, row.group))
        for key, (category, group) in self.alias.items():
            if key in self.conflicts:
                self.alias.pop(key, None)
        # 内容指纹：同一张表存成 CSV 和 XLSX 时字节不同，但内容相同，用它比较才算数。
        self.content_key = tuple(sorted({(normalize(row.category), normalize(row.group)) for row in self.rows}))

    # ---- 查询 ----
    def resolve(self, category):
        raw = "" if category is None else str(category).strip()
        key = normalize(raw)
        if not key:
            return Match(raw, FALLBACK_GROUP, "未匹配", "细分为空")
        if raw in NON_BRAND:
            return Match(raw, FALLBACK_GROUP, "未匹配", "服务设施/非独立品牌，不参与业态归并")
        if key in self.exact and key not in self.conflicts:
            std, group = self.exact[key]
            return Match(std, group, "精确", "")
        if key in self.conflicts:
            return Match(raw, FALLBACK_GROUP, "歧义",
                         f"对照表中“{raw}”对应多个标准业态（{'、'.join(sorted(self.conflicts[key]))}）")
        if key in self.alias:
            std, group = self.alias[key]
            return Match(std, group, "表内别名", "")
        # 内置归并只用来"认出平台原文对应哪个细分业态"，标准业态必须以对照表为准：
        # 表里没有这个细分业态就不猜，直接进待补清单，由使用者决定怎么归类。
        builtin = BUILTIN_ALIAS.get(key)
        by_alias = builtin is not None
        if builtin is None:
            builtin = next((target for needle, target in KEYWORD_RULES if normalize(needle) in key), None)
        if builtin is not None:
            std_key = normalize(builtin)
            if std_key in self.exact:
                std, group = self.exact[std_key]
                return Match(std, group, "内置别名" if by_alias else "关键词", "")
            return Match(raw, FALLBACK_GROUP, "未匹配",
                         f"平台原文“{raw}”按内置归并应归“{builtin}”，但对照表里没有这个细分业态，"
                         f"补一行（细分业态={builtin}）后重新整理即可")
        return Match(raw, FALLBACK_GROUP, "未匹配", "对照表和内置归并都无法确定标准业态")

    def describe(self):
        name = self.source.name if self.source else "内置业态对照"
        parts = [f"{len(self.groups)}类标准业态", f"{len(self.exact)}个细分业态"]
        if self.alias:
            parts.append(f"{len(self.alias)}条表内别名")
        if self.conflicts:
            parts.append(f"{len(self.conflicts)}条重复")
        return f"{name}（{'，'.join(parts)}）"


class DictMapping:
    """兼容旧调用：直接传 {细分业态: 标准业态} 字典。"""

    def __init__(self, mapping):
        self.mapping = {normalize(k): (k, v) for k, v in mapping.items()}
        self.groups = list(dict.fromkeys(v for _, v in self.mapping.values()))
        self.source, self.mtime, self.fingerprint, self.warnings = None, None, "", []
        self.conflicts = {}
        self.alias = {}
        self.content_key = tuple(sorted(self.mapping))

    def resolve(self, category):
        raw = "" if category is None else str(category).strip()
        found = self.mapping.get(normalize(raw))
        if found:
            return Match(raw, found[1], "精确", "")
        return Match(raw, FALLBACK_GROUP, "未匹配", "自定义对照未包含")

    def describe(self):
        return f"自定义对照（{len(self.mapping)}个细分业态）"


def default_mapping():
    rows = [TableRow(category, group) for category, group in DEFAULT_ROWS]
    return BusinessMapping(rows, check_duplicates=False)


def coerce_mapping(mapping):
    if isinstance(mapping, (BusinessMapping, DictMapping)):
        return mapping
    if isinstance(mapping, dict):
        return DictMapping(mapping)
    if mapping is None:
        return default_mapping()
    raise TypeError(f"不支持的对照表类型：{type(mapping).__name__}")


# ---------------------------------------------------------------- 读取 CSV
def _decode(data):
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", "replace")


def _sniff_delimiter(sample):
    """按"出现在最多行里"判定分隔符；首行常是标题，不能只看第一行。"""
    lines = [line for line in sample.splitlines()[:12] if line.strip()]
    if not lines:
        return ","
    best, best_hits = ",", 0
    for delimiter in (",", "\t", ";", "|"):
        hits = sum(1 for line in lines if delimiter in line)
        if hits > best_hits:
            best, best_hits = delimiter, hits
    return best


def _rows_to_mapping(matrix, source, mtime, fingerprint):
    header_index, columns = None, {}
    for index, row in enumerate(matrix[:30]):
        roles = {}
        for position, cell in enumerate(row):
            role = _header_key(cell)
            if role and role not in roles:
                roles[role] = position
        if "category" in roles and "group" in roles:
            header_index, columns = index, roles
            break
    if header_index is None:
        raise MappingError("对照表缺少“细分业态”“标准业态”两列表头")
    rows, warnings = [], []
    for row in matrix[header_index + 1:]:
        def cell(role):
            position = columns.get(role)
            if position is None or position >= len(row):
                return ""
            return str(row[position]).strip()
        category, group_cell = cell("category"), cell("group")
        if not category and not group_cell:
            continue
        if not category:
            warnings.append(f"忽略只有标准业态没有细分业态的行：{group_cell}")
            continue
        # 有的表把别名直接写在"标准业态"格里（如"餐饮;奶茶;鲜榨"），第一个值是标准业态，其余当别名。
        parts = [part.strip() for part in re.split(r"[;；]", group_cell) if part.strip()]
        group, extra = (parts[0], parts[1:]) if parts else ("", [])
        if not group:
            warnings.append(f"忽略标准业态为空的行：{category}")
            continue
        aliases = [part.strip() for part in re.split(r"[;；]", cell("alias")) if part.strip()] + extra
        rows.append(TableRow(category, group, aliases))
    if not rows:
        raise MappingError("对照表没有可用的数据行（只有表头）")
    return BusinessMapping(rows, source, mtime, fingerprint, warnings)


def read_csv_table(path):
    data = Path(path).read_bytes()
    text = _decode(data).lstrip("\ufeff")
    delimiter = _sniff_delimiter(text[:4096])
    matrix = [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]
    fingerprint = hashlib.sha256(data).hexdigest()[:12]
    return _rows_to_mapping(matrix, path, Path(path).stat().st_mtime, fingerprint)


# ---------------------------------------------------------------- 读取 XLSX
def _cell_value(cell, shared):
    kind = cell.get("t")
    if kind == "inlineStr":
        node = cell.find(f"{{{NS}}}is")
        return "".join(node.itertext()) if node is not None else ""
    value = cell.find(f"{{{NS}}}v")
    if value is None or value.text is None:
        node = cell.find(f"{{{NS}}}is")
        return "".join(node.itertext()) if node is not None else ""
    text = value.text
    if kind == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return text
    if kind == "b":
        return "TRUE" if text == "1" else "FALSE"
    return text


def _column_index(reference):
    letters = re.match(r"[A-Z]+", reference or "A")
    number = 0
    for char in letters[0] if letters else "A":
        number = number * 26 + ord(char) - 64
    return max(number, 1)


def xlsx_sheets(path):
    """按工作簿顺序返回 [(工作表名, 二维值列表)]，只用标准库。"""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        relations = {}
        if "xl/_rels/workbook.xml.rels" in names:
            relations = {node.get("Id"): node.get("Target")
                         for node in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = []
        for sheet in workbook.findall(f"{{{NS}}}sheets/{{{NS}}}sheet"):
            target = relations.get(sheet.get(f"{{{REL}}}id"), "")
            part = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if not part or part not in names:
                continue
            document = ET.fromstring(archive.read(part))
            matrix = []
            for row in document.findall(f"{{{NS}}}sheetData/{{{NS}}}row"):
                values = []
                for cell in row.findall(f"{{{NS}}}c"):
                    position = _column_index(cell.get("r"))
                    while len(values) < position - 1:
                        values.append("")
                    values.append(_cell_value(cell, shared))
                matrix.append(values)
            sheets.append((sheet.get("name", ""), matrix))
        return sheets


def read_xlsx_table(path):
    data = Path(path).read_bytes()
    fingerprint = hashlib.sha256(data).hexdigest()[:12]
    errors = []
    for name, matrix in xlsx_sheets(path):
        try:
            return _rows_to_mapping(matrix, path, Path(path).stat().st_mtime, fingerprint)
        except MappingError as exc:
            errors.append(f"“{name}”：{exc}")
    raise MappingError("Excel 里没有找到含“细分业态”“标准业态”表头的工作表；" + "；".join(errors))


def read_table(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"业态对照表不存在：{path}")
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return read_xlsx_table(path)
    return read_csv_table(path)


# ---------------------------------------------------------------- 自动发现
def _candidate_dirs(hints):
    """[(优先级, 目录)]：靠前的 hint 优先级高（程序目录 > 输出目录 > 数据目录）。"""
    seen, result = set(), []
    for priority, hint in enumerate(hint for hint in hints if hint):
        path = Path(hint).expanduser()
        try:
            path = path.resolve()
        except OSError:
            continue
        current = path if path.is_dir() else path.parent
        for _ in range(3):  # 本目录、上一级、上两级：表常放在"采集数据"或便携套装根目录
            for candidate in (current, current / "Excel模板", current / "模板", current / "templates"):
                key = str(candidate).lower()
                if key in seen or not candidate.is_dir():
                    continue
                seen.add(key)
                result.append((priority, candidate))
            if current.parent == current:
                break
            current = current.parent
    return result


def _table_candidates(directory):
    found = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.is_file() or entry.name.startswith("~$") or entry.name.startswith("."):
            continue
        if entry.suffix.lower() not in TABLE_SUFFIXES:
            continue
        if TABLE_MARK in entry.name or normalize(entry.stem) in {normalize("业态对照表"), normalize("对照表")}:
            found.append(entry)
    return found


def _place(path):
    """提示里用哪一级目录指代这份表：模板目录只说"Excel模板"会分不清是哪套。"""
    path = Path(path)
    parent = path.parent
    if normalize(parent.name) in {normalize("Excel模板"), normalize("模板"), normalize("templates")}:
        parent = parent.parent
    return parent.name or str(parent)


def discover_table(hints=(), explicit=None):
    """找出该用的业态对照表。

    优先用显式指定的文件；否则在 EXE 所在目录、Excel模板 目录等位置找含"业态"的
    CSV/XLSX，取修改时间最新的那一份。返回 (mapping 或 None, 选用路径, 说明, 候选列表)。
    """
    explicit_note = ""
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            try:
                mapping = read_table(path)
                return mapping, path, "手工指定", [path]
            except (MappingError, OSError, zipfile.BadZipFile) as exc:
                explicit_note = f"手工指定的对照表不可用（{exc}），已改用自动识别；"
    candidates, skipped, seen = [], [], set()
    for priority, directory in _candidate_dirs(list(hints) + ([explicit] if explicit else [])):
        for entry in _table_candidates(directory):
            key = str(entry).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                candidates.append((entry, entry.stat().st_mtime, priority))
            except OSError:
                continue
    # 位置优先（程序目录 > 输出目录 > 数据目录），同一位置内取修改时间最新的那份。
    candidates.sort(key=lambda item: (item[2], -item[1]))
    read, notes = [], []
    for entry, mtime, priority in candidates:
        try:
            read.append((read_table(entry), entry, mtime))
        except (MappingError, OSError, zipfile.BadZipFile, ValueError) as exc:
            skipped.append(f"{entry.name}（{entry.parent.name}）：{exc}")
    if not read:
        parts = [explicit_note] if explicit_note else []
        if skipped:
            parts.append("跳过无效文件：" + "；".join(skipped) + "。")
        if not candidates:
            parts.append("所在目录没有业态对照表。")
        parts.append("未找到可用对照表，改用内置四类业态。")
        return None, None, "".join(parts), [item[0] for item in candidates]
    mapping, path, mtime = read[0]
    others = [f"{item[1].name}（{_place(item[1])}）" for item in read[1:4]]
    if len(read) > 4:
        others.append(f"等{len(read) - 1}份")
    note = "自动识别：优先程序目录，同一位置取修改时间最新的一份"
    if others:
        note += "；另有可用版本未采用：" + "、".join(others)
    if skipped:
        note += "；跳过无效文件：" + "；".join(skipped)
    if explicit_note:
        note = explicit_note + note
    if others and len({item[0].content_key for item in read}) > 1:
        note += "；多份对照表内容不一致，如需改用另一份，请在“业态对照表”里手工指定"
    return mapping, path, note, [item[0] for item in candidates]


# ---------------------------------------------------------------- 写回
def save_mapping(path, mapping=None):
    """确保对照表存在。新建时写成"细分业态,标准业态,别名"三列，仍兼容两列。"""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        if isinstance(mapping, BusinessMapping):
            for row in mapping.rows:
                rows.append([row.category, row.group, ";".join(row.aliases)])
        else:
            base = mapping if isinstance(mapping, dict) else dict(DEFAULT_ROWS)
            for category, group in base.items():
                rows.append([category, group, ""])
        with path.open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["细分业态", "标准业态", ALIAS_KEY])
            writer.writerows(rows)
    return path


def builtin_rows():
    """发行版默认对照表：标准细分业态 + 平台别名，便于用户直接改。"""
    rows = []
    for group, targets in BUILTIN_GROUPS.items():
        for target, names in targets.items():
            extras = [name for name in names if normalize(name) != normalize(target)]
            rows.append(TableRow(target, group, extras))
    return rows
