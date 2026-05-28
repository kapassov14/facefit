from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


AgingTypeId = Literal["muscular", "deformation_edema", "fine_wrinkle", "tired_mixed"]
Confidence = Literal["low", "medium", "high"]
ZoneStatus = Literal["green", "yellow", "orange", "red"]

PROTOCOL_VERSION = "bella_face_protocol_v4"

AGING_TYPE_NAMES: dict[str, str] = {
    "muscular": "Мускульный",
    "deformation_edema": "Деформационно-отечный",
    "fine_wrinkle": "Мелкоморщинистый",
    "tired_mixed": "Усталый / смешанный",
}

AGING_KNOWLEDGE_BASE: dict[str, dict[str, Any]] = {
    "muscular": {
        "characteristic": "Развитая мимическая мускулатура и малое количество подкожно-жировой клетчатки. Сильные мышцы плотно спаяны с кожей, овал может долго оставаться четким.",
        "mechanism": "Хронический гипертонус жевательных, височных, лобной и круговой мышцы глаза стягивает кожу в глубокие заломы.",
        "clinical": ["межбровье", "лоб", "гусиные лапки", "напряжение жевательных мышц"],
        "risk": "Мимические морщины переходят в статические борозды, ткани в местах зажимов фиброзируются, асимметрия может нарастать.",
        "signs": ["мышцы зажаты", "лицо выглядит напряженным и строгим даже в покое"],
        "main_zones": ["межбровье", "лоб", "жевательные", "круговая мышца глаза"],
        "long_term": "сначала формируются резкие вертикальные морщины в межбровье, затем рубленые носогубные складки из-за мышечного зажима",
        "main_focus": "расслабление, снятие гипертонуса, мягкость мимики",
    },
    "deformation_edema": {
        "characteristic": "Сценарий со склонностью к задержке жидкости, избытку мягких тканей и утяжелению нижней трети.",
        "mechanism": "Под весом подкожного жира и лимфостаза ткани смещаются вниз; зажатая шея и сутулость замедляют отток жидкости.",
        "clinical": ["потеря четкости овала", "отечность под глазами", "второй подбородок", "тяжелая нижняя треть"],
        "risk": "Хронический застой лимфы растягивает связочный аппарат и кожу, утренняя припухлость переходит в выраженную тяжесть нижней трети.",
        "signs": [
            "склонность к отекам и задержке жидкости",
            "мягкость тканей",
            "потеря четкости овала",
            "мешки под глазами",
            "тяжелая нижняя треть",
        ],
        "main_zones": ["лимфоток", "отечность", "шея", "осанка", "нижняя треть", "овал"],
        "long_term": "утренняя одутловатость частично проходит к вечеру, затем ткани растягиваются, тяжелеют и дают пастозность контуров",
        "main_focus": "лимфодренаж, шея, осанка, отток жидкости, поддержка овала",
    },
    "fine_wrinkle": {
        "characteristic": "Тип печеного яблока: сухая тонкая кожа, астеничная база и быстрое истончение тканей при сохранении контура.",
        "mechanism": "Дефицит собственных липидов, обезвоживание дермы, истощение подкожно-жировой основы и замедление кровотока.",
        "clinical": ["мелкая сетка морщин", "кисетные морщины вокруг губ", "ранняя пигментация", "четкий овал"],
        "risk": "Кожа теряет эластичность и сильнее обтягивает костную основу, лицо выглядит суше из-за дефицита объема.",
        "signs": [
            "сухость и тонкость кожи",
            "мелкая сетка морщин",
            "дефицит объема",
            "кожа быстрее теряет эластичность",
        ],
        "main_zones": ["сухость", "тонкость кожи", "мелкая сетка", "увлажнение", "питание тканей"],
        "long_term": "первыми проваливаются виски и щеки, губы истончаются, кожа вокруг глаз и на щеках покрывается сеточкой",
        "main_focus": "увлажнение, питание тканей, микроциркуляция, мягкая работа с мышцами",
    },
    "tired_mixed": {
        "characteristic": "Усталый / смешанный сценарий: лицо может выглядеть свежим утром, но уставать к вечеру; признаки разных морфотипов распределяются неравномерно.",
        "mechanism": "Снижение тонуса мышц, ухудшение микроциркуляции, легкая пастозность и сочетание нескольких механизмов в разных зонах.",
        "clinical": ["зона глаз", "носослезная борозда", "носогубные складки", "уголки рта", "снижение сияния кожи"],
        "risk": "Пастозность, дефицит объемов и визуальное ощущение невыспавшегося лица; нужен комплекс лимфодренажа, расслабления и увлажнения.",
        "signs": ["лицо выглядит уставшим", "снижение свежести", "легкая пастозность"],
        "main_zones": ["зона глаз", "носослезная зона", "носогубка", "уголки рта", "свежесть"],
        "long_term": "уголки рта опускаются, углубляется носослезная борозда и носогубные складки, лицо быстрее теряет свежесть к вечеру",
        "main_focus": "вернуть свежесть, мягкий тонус, микроциркуляцию, расслабление",
    },
}

FORBIDDEN_PHRASES: list[str] = [
    "тип лица",
    "овальный тип лица",
    "прямоугольный тип лица",
    "круглый тип лица",
    "визуально не определено",
    "проблема",
    "100%",
    "гарантированно",
    "минус 10 лет",
    "птозный",
    "устало-отечный",
    "устало-отёчный",
    "комбинированный тип",
]

COPIED_EXAMPLE_PHRASES: list[str] = [
    "До эффекта Glass Skin вам ближе чем кажется",
    "До эффекта Glass Skin вам ближе, чем кажется",
    "Фейс-фитнес для вашего типа — это прежде всего раскрытие вашей настоящей красоты",
    "Фейс-фитнес для вашего типа - это прежде всего раскрытие вашей настоящей красоты",
    "У вас овально-прямоугольное лицо",
    "Скулы дают лицу естественный лифтинг",
    "Глаза выразительные с красивым разрезом",
    "Плотная ровная кожа хорошо держит форму лица",
    "это настоящий актив который будет работать на вас с возрастом",
    "Именно для этого создана система Bella Vladi",
    "Именно для этого создан курс Bella Vladi",
    "Вы посмотрите в зеркало — и увидите себя настоящую",
    "Вы посмотрите в зеркало - и увидите себя настоящую",
]

GENERIC_TEMPLATE_PHRASES: list[str] = [
    "Кожа выглядит ухоженной; визуальный возраст больше задают",
    "Кожа выглядит ухоженной и живой",
    "По фото больше внимания просит",
    "У вас гармоничная форма лица: на фото особенно красиво читается",
    "У вас гармоничная форма лица, скулы дают опору",
    "Форма, скулы, взгляд, симметрия и пропорции выглядят природным активом",
    "Фейс-фитнес здесь не меняет черты, а раскрывает вашу природную базу",
    "Фейсфитнес здесь помогает мягко проявить сильные стороны лица",
    "Сильная природная база уже видна",
    "По логике типа работа идет через",
    "Первый маршрут текущего фото",
    "Главный маршрут сейчас",
    "Главное сейчас — мягко поддержать ключевые зоны",
    "первые зоны могут выглядеть мягче и свежее",
    "главный фокус станет заметнее в отражении",
    "эффект регулярности может стать устойчивее",
]

FORECAST_PERIODS = ["Через 2 недели", "Через 3–4 недели", "Через 6–8 недель"]

TEXT_LIMITS: dict[str, int] = {
    "skin_visual_age.text": 180,
    "skin_type.text": 220,
    "face_strengths.text": 340,
    "aging_type.text": 620,
    "future_changes.text": 620,
    "age_changes.text": 430,
    "face_fitness_benefits.text": 340,
    "time_forecast.items.text": 90,
    "growth_zones.summary": 140,
    "final_summary.text": 360,
    "final_summary.quote": 90,
}

MIXED_COMPONENT_NAMES: dict[str, str] = {
    "tired": "Усталый",
    "muscular": "Мускульный",
    "deformation_edema": "Деформационно-отечный",
    "fine_wrinkle": "Мелкоморщинистый",
}

MIXED_COMPONENT_CHARACTERISTICS: dict[str, str] = {
    "tired": (
        "усталый сценарий связан со снижением тонуса и микроциркуляции; к вечеру быстрее читаются зона глаз, "
        "носослезная линия, носогубка и уголки рта"
    ),
    "deformation_edema": (
        "деформационно-отечный сценарий связан с задержкой жидкости, мягкостью тканей, шеей и осанкой; "
        "под глазами может появляться отечность, а овал и нижняя треть требуют лимфотока"
    ),
    "muscular": (
        "мускульный сценарий связан с гипертонусом жевательных, лба, межбровья и круговой мышцы глаза; "
        "сильные мышцы могут стягивать кожу в более глубокие заломы"
    ),
    "fine_wrinkle": (
        "мелкоморщинистый сценарий связан с сухостью, тонкостью кожи, питанием тканей и микроциркуляцией; "
        "первой проявляется мелкая сеточка и потеря мягкой основы"
    ),
}

MIXED_COMPONENT_FOCUS: dict[str, str] = {
    "tired": "свежесть, мягкий тонус и микроциркуляция",
    "deformation_edema": "лимфодренаж, шея, осанка и поддержка овала",
    "muscular": "расслабление гипертонуса, межбровья, лба и жевательных",
    "fine_wrinkle": "увлажнение, питание тканей и мягкая микроциркуляция",
}

SKIN_TYPE_NAMES: tuple[str, ...] = (
    "Комбинированная, склонная к обезвоженности",
    "Сухая, склонная к обезвоженности",
    "Комбинированная, активная в T-зоне",
    "Чувствительная, реактивная",
    "Комбинированная, с ровной плотной базой",
)

SKIN_TYPE_TEXTS: dict[str, str] = {
    "combination_dehydrated": (
        "У вас комбинированная кожа с легкой склонностью к обезвоженности. Плюс этого типа — кожа хорошо держит каркас лица. "
        "Центральная зона просит больше влаги; при мягком уходе тон выглядит свежее, ровнее и более сияющим."
    ),
    "dry_dehydrated": (
        "У вас сухая кожа, склонная к обезвоженности. Плюс этого типа — деликатная текстура и мягкий ровный тон без лишнего блеска. "
        "Ей важны питание и влага; при бережном уходе лицо выглядит свежее и спокойнее."
    ),
    "combination_tzone": (
        "У вас комбинированная кожа с активной T-зоной. Плюс этого типа — плотность и хороший ресурс каркаса лица. "
        "Центру важны баланс себума и увлажнение; при ровном уходе кожа выглядит чище, свежее и мягче."
    ),
    "sensitive_reactive": (
        "У вас чувствительная, реактивная кожа. Плюс этого типа — она быстро отвечает на бережный уход и спокойный ритм. "
        "Ей важны восстановление и мягкое увлажнение; тогда тон выглядит ровнее, свежее и более ухоженно."
    ),
    "combination_dense": (
        "У вас комбинированная кожа с ровной плотной базой. Плюс этого типа — кожа хорошо держит каркас лица. "
        "Зона глаз и центр лица просят больше увлажнения; при регулярном уходе тон выглядит свежее и ровнее."
    ),
}

SKIN_POSITIVE_MARKERS: tuple[str, ...] = ("плюс", "хорош", "держит", "ровн", "плот", "ухож", "ресурс")
SKIN_FEATURE_MARKERS: tuple[str, ...] = (
    "просит",
    "важн",
    "склон",
    "зона",
    "центр",
    "t-зон",
    "т-зон",
    "увлаж",
    "влага",
    "себум",
    "реактив",
    "сух",
)
SKIN_POTENTIAL_MARKERS: tuple[str, ...] = (
    "при",
    "может",
    "выглядит",
    "будет",
    "свеже",
    "ровнее",
    "сия",
    "ухож",
    "мягче",
    "спокойнее",
)

LIST_LIMITS: dict[str, int] = {
    "skin_type.bullets": 2,
    "face_strengths.bullets": 3,
    "future_changes.bullets": 2,
    "face_fitness_benefits.bullets": 3,
}

TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    "muscular": (
        "межбров",
        "лоб",
        "жеватель",
        "гипертонус",
        "напряж",
        "мимичес",
        "зажим",
        "маска напряжения",
    ),
    "deformation_edema": (
        "лимф",
        "отек",
        "отёк",
        "пастоз",
        "шея",
        "осанк",
        "нижн",
        "овал",
        "мягк",
        "отток",
    ),
    "fine_wrinkle": (
        "сух",
        "тонк",
        "мелк",
        "сетк",
        "увлаж",
        "питани",
        "микроциркуля",
        "эластич",
        "текстур",
    ),
    "tired_mixed": (
        "глаз",
        "носослез",
        "носослёз",
        "носогуб",
        "уголк",
        "устал",
        "свеж",
        "пастоз",
        "микроциркуля",
        "тонус",
    ),
}

STRONG_FOREIGN_PATTERNS: dict[str, tuple[str, ...]] = {
    "muscular": ("маска напряжения", "гипертонус", "жеватель", "межбров.*главн", "лоб.*главн"),
    "deformation_edema": ("лимф", "отеч", "отёч", "нижн.*треть", "шея.*лимф", "осанк"),
    "fine_wrinkle": ("мелк.*сетк", "тонк.*кож", "сух", "увлажн.*главн", "питани.*ткан"),
    "tired_mixed": ("устал.*вид", "носогуб", "уголк.*рта", "носослез", "носослёз", "свежест"),
}

FACE_STRENGTH_MARKERS: dict[str, tuple[str, ...]] = {
    "форма лица / овал": ("форма", "овал", "контур", "линия лица"),
    "скулы / костная база": ("скул", "костн", "опор", "лифтинг"),
    "глаза / взгляд": ("глаз", "взгляд", "разрез", "веки"),
    "симметрия / пропорции": ("симметр", "пропорц", "гармони", "баланс"),
    "природный актив / эффект процедур": ("природ", "от природы", "процедур", "актив", "дано"),
}

FUTURE_CHANGE_MARKERS: dict[str, tuple[str, ...]] = {
    "muscular": ("межбров", "лоб", "залом", "напряж", "покой", "гипертонус", "мимичес"),
    "deformation_edema": ("лимф", "отек", "отеч", "отёк", "шея", "овал", "нижн", "ткан", "тяжел"),
    "fine_wrinkle": ("сух", "тонк", "мелк", "сетк", "увлаж", "питани", "микроциркуля", "эластич"),
    "tired_mixed": ("глаз", "носослез", "носослёз", "носогуб", "уголк", "вечер", "устал", "свеж", "тонус"),
}

MIXED_COMPONENT_MARKERS: dict[str, tuple[str, ...]] = {
    "tired": TYPE_MARKERS["tired_mixed"],
    "muscular": TYPE_MARKERS["muscular"],
    "deformation_edema": TYPE_MARKERS["deformation_edema"],
    "fine_wrinkle": TYPE_MARKERS["fine_wrinkle"],
}

MIXED_COMPONENT_ALIASES: dict[str, str] = {
    "tired": "tired",
    "устал": "tired",
    "tired_mixed": "tired",
    "muscular": "muscular",
    "мускул": "muscular",
    "deformation": "deformation_edema",
    "deformation_edema": "deformation_edema",
    "деформац": "deformation_edema",
    "отеч": "deformation_edema",
    "отёч": "deformation_edema",
    "fine_wrinkle": "fine_wrinkle",
    "wrinkle": "fine_wrinkle",
    "мелкоморщ": "fine_wrinkle",
}

MIXED_AGING_COMPONENT_TEXTS: dict[str, str] = {
    "deformation_edema": (
        "Что происходит внутри\n\nГлавная зона внимания — застой лимфы и нарушение микроциркуляции. Наши мимические мышцы работают как «насос», проталкивающий жидкость. Если они в спазме или, наоборот, слишком слабы, лимфодренаж останавливается. Ситуацию усугубляет нарушение статики шеи: зажатые мышцы и сутулость буквально перекрывают пути оттока жидкости от лица."
    ),
    "muscular": (
        "Характеристика этого типа\n\nОтдельные группы мышц находятся в состоянии хронического гипертонуса, особенно жевательные, височные, лобная и круговая мышца глаза. Они буквально «каменеют», укорачиваются и стягивают кожу в глубокие заломы. Мышцы-антагонисты без должной нагрузки слабеют и атрофируются."
    ),
    "fine_wrinkle": (
        "Характеристика этого типа\n\nОсновной процесс — истощение тканей. Подкожно-жировой слой не смещается вниз, а буквально «тает», из-за чего кожа лишается своей естественной мягкой основы. Мышцы от природы тонкие и без нагрузки быстро слабеют. Кровоток замедляется, кожа перестает получать питание изнутри."
    ),
}

MIXED_FUTURE_COMPONENT_TEXTS: dict[str, str] = {
    "tired": "зона глаз, носослезная линия, носогубка и уголки рта быстрее дают ощущение усталости к вечеру; коже важны свежесть, тонус и микроциркуляция",
    "deformation_edema": "утренняя одутловатость может проходить медленнее, ткани растягиваются и тяжелеют, под глазами держится отечность, а овал и нижняя треть требуют лимфотока",
    "muscular": "межбровье, лоб и жевательные могут фиксировать мимические заломы; гипертонус делает выражение строже, даже когда лицо расслаблено",
    "fine_wrinkle": "кожа быстрее теряет влагу и эластичность, вокруг глаз и на щеках появляется мелкая сеточка, а лицу важны питание тканей и микроциркуляция",
}

MIXED_AGE_COMPONENT_TEXTS: dict[str, str] = {
    "tired": "к вечеру сильнее читаются зона глаз, носослезка, носогубка и уголки рта",
    "deformation_edema": "дольше держатся утренняя одутловатость, отечность под глазами и мягкость овала",
    "muscular": "быстрее фиксируются межбровье, лоб, мимические заломы и жевательное напряжение",
    "fine_wrinkle": "заметнее сухость, мелкая сетка вокруг глаз и потеря объема в щеках",
}

FUTURE_SUPPORT_MARKERS: tuple[str, ...] = (
    "без",
    "если не",
    "без поддержки",
    "без ухода",
    "без работы",
    "без регуляр",
    "не поддерж",
    "сначала",
    "затем",
    "со временем",
    "склонно",
    "начинает",
    "появляется",
    "после",
)

FUTURE_FEAR_WORDS: tuple[str, ...] = (
    "катастроф",
    "ужас",
    "необратим",
    "навсегда",
    "резко состар",
    "разруш",
)

FUTURE_CHANGE_TEXTS: dict[str, str] = {
    "muscular": (
        "Как меняется лицо со временем\n\nСначала формируются резкие вертикальные морщины в межбровье. Затем проявляются «рубленые» носогубные складки из-за жесткого мышечного зажима. Гипертонус жевательных делает лицо визуально более квадратным и тяжелым."
    ),
    "deformation_edema": (
        "Как меняется лицо со временем\n\nЛицо склонно к «утренней одутловатости», которая лишь частично проходит к вечеру. Из-за постоянного присутствия лишней жидкости ткани растягиваются и тяжелеют. Под глазами формируются стойкие отечные мешки, появляется пастозность и «лунообразность» контуров. Цвет лица становится тусклым или сероватым из-за плохого кровоснабжения. После 40 лет перерастянутая жидкостью кожа окончательно теряет ресурс упругости, и отечность переходит в тяжелый гравитационный птоз."
    ),
    "fine_wrinkle": (
        "Как меняется лицо со временем\n\nЛицо начинает терять объемы: первыми проваливаются виски и щеки, губы истончаются. Кожа вокруг глаз и на щеках покрывается мелкой сеточкой. Контур может оставаться четким, но лицо выглядит старше из-за сухости."
    ),
    "tired_mixed": (
        "Как меняется лицо со временем\n\nСначала лицо выглядит свежим утром, но устает к вечеру. Затем углубляются носослезная борозда и носогубные складки, опускаются уголки рта, уходит сияние кожи. Появляется ощущение невыспавшегося лица."
    ),
}

AGING_TYPE_TEXTS: dict[str, str] = {
    "muscular": (
        "Характеристика этого типа\n\nОтдельные группы мышц находятся в состоянии хронического гипертонуса, особенно жевательные, височные, лобная и круговая мышца глаза. Они буквально «каменеют», укорачиваются и стягивают кожу в глубокие заломы. В то же время мышцы-антагонисты, например щечные и подбородочные, без должной нагрузки слабеют и атрофируются. Возникает критический дисбаланс натяжения тканей."
    ),
    "deformation_edema": (
        "Что происходит внутри\n\nГлавная зона внимания — застой лимфы и нарушение микроциркуляции. Наши мимические мышцы работают как «насос», проталкивающий жидкость. Если они в спазме или, наоборот, слишком слабы, лимфодренаж останавливается. Ситуацию усугубляет нарушение статики шеи: зажатые мышцы и сутулость буквально перекрывают пути оттока жидкости от лица."
    ),
    "fine_wrinkle": (
        "Характеристика этого типа\n\nОсновной процесс — истощение тканей. Подкожно-жировой слой не смещается вниз, а словно тает, поэтому кожа теряет естественную мягкую основу. Мышцы от природы тонкие и без нагрузки быстро слабеют. Кровоток замедляется, кожа получает меньше питания изнутри."
    ),
    "tired_mixed": (
        "Характеристика этого типа\n\nУсталый тип связан со снижением тонуса мышц и ухудшением микроциркуляции. Лицо выглядит свежим утром, но «устает» к вечеру. Первыми становятся заметнее опущение уголков рта, носослезная борозда, носогубные складки и потеря сияния кожи."
    ),
}

FACE_STRENGTH_TEXTS: dict[str, str] = {
    "muscular": (
        "У вас выразительное лицо с сильной природной базой: форма держит четкость, скулы дают опору, а взгляд сразу притягивает внимание. "
        "Гармоничные пропорции выглядят дорого и собранно; важно лишь смягчить напряжение, чтобы природная красота читалась легче."
    ),
    "deformation_edema": (
        "У вас мягкое женственное лицо с красивой природной базой: гармоничная форма, скулы и взгляд уже создают приятное первое впечатление. "
        "Это те черты, которые многие стремятся подчеркнуть процедурами, а у вас они есть от природы; задача — добавить легкости и четкости."
    ),
    "fine_wrinkle": (
        "У вас деликатное, изящное лицо с красивым контуром и выразительной зоной глаз. Скулы и пропорции дают природную опору, "
        "а тонкая фактура делает черты утонченными; при питании тканей эта красота раскрывается особенно мягко."
    ),
    "tired_mixed": (
        "У вас красивое лицо с мягкой гармоничной формой, выразительными глазами и природной скуловой опорой. "
        "В пропорциях уже есть баланс, который многие хотят получить через процедуры; фейс-фитнес здесь помогает просто проявить то, что у вас уже есть."
    ),
}

FACE_STRENGTH_BULLETS: dict[str, list[str]] = {
    "muscular": [
        "Четкая форма лица выглядит собранно и выразительно.",
        "Скулы и костная база дают красивую природную опору.",
        "Взгляд станет мягче, когда уйдет лишнее напряжение.",
    ],
    "deformation_edema": [
        "Мягкая форма лица выглядит женственно и гармонично.",
        "Скулы дают базу для красивой четкости овала.",
        "Взгляд и пропорции уже создают приятное первое впечатление.",
    ],
    "fine_wrinkle": [
        "Изящный контур и скулы дают лицу тонкую выразительность.",
        "Глаза красиво читаются и могут стать еще свежее.",
        "Пропорции выглядят природно гармонично.",
    ],
    "tired_mixed": [
        "Мягкая форма лица и скулы дают красивую природную базу.",
        "Глаза — сильная зона, через них быстро возвращается свежесть.",
        "Пропорции гармоничные: их хочется не менять, а раскрывать.",
    ],
}

FACE_FITNESS_BENEFIT_TEXTS: dict[str, str] = {
    "muscular": (
        "Фейс-фитнес именно для вас — это не «качать лицо», а вернуть мягкость сильной мышечной базе. "
        "Когда расслабятся межбровье, лоб и жевательные, взгляд станет спокойнее, черты мягче, а четкий овал будет выглядеть еще благороднее."
    ),
    "deformation_edema": (
        "Фейс-фитнес для вас начнет работать через шею, осанку и лимфодренаж. Когда улучшится отток, зона глаз выглядит легче, "
        "нижняя треть меньше утяжеляет лицо, а природные скулы и овал становятся заметнее."
    ),
    "fine_wrinkle": (
        "Фейс-фитнес для вашего типа — это мягкое питание тканей изнутри: микроциркуляция, бережный тонус и увлажнение. "
        "Лицо может выглядеть более живым, кожа — спокойнее и свежее, а изящный контур сохранит свою природную красоту."
    ),
    "tired_mixed": (
        "Фейс-фитнес для вас — способ вернуть лицу отдохнувшее выражение без изменения черт. Работа с шеей, лимфотоком и мягким тонусом "
        "освежает взгляд, смягчает носогубную зону и помогает уголкам рта выглядеть легче."
    ),
}

FACE_FITNESS_BENEFIT_BULLETS: dict[str, list[str]] = {
    "muscular": [
        "Межбровье и лоб расслабятся — взгляд станет мягче.",
        "Жевательная зона отпустит лишнюю строгость.",
        "Четкий овал будет выглядеть спокойнее и благороднее.",
    ],
    "deformation_edema": [
        "Шея и лимфоток помогут зоне глаз выглядеть легче.",
        "Нижняя треть станет визуально менее тяжелой.",
        "Овал и скулы будут читаться собраннее.",
    ],
    "fine_wrinkle": [
        "Микроциркуляция даст коже больше живости.",
        "Мягкий тонус поддержит объем без перегруза.",
        "Изящный контур будет выглядеть свежее.",
    ],
    "tired_mixed": [
        "Взгляд станет свежее за счет микроциркуляции.",
        "Носогубная зона и уголки рта будут мягче.",
        "Лицо будет выглядеть более отдохнувшим.",
    ],
}

FINAL_SUMMARY_TEXTS: dict[str, str] = {
    "muscular": "У вас красивое лицо с сильной природной базой. Главное сейчас — снять напряжение, которое делает черты строже и скрывает вашу настоящую мягкость. Именно для этого создан этот курс.",
    "deformation_edema": "У вас красивое лицо с мягкой женственной базой. Главное сейчас — вернуть тканям легкость, поддержать шею и овал, чтобы природные черты раскрылись яснее. Именно для этого создан этот курс.",
    "fine_wrinkle": "У вас красивое, изящное лицо с тонкой природной выразительностью. Главное сейчас — напитать ткани, оживить кровоток и вернуть коже свежесть. Именно для этого создан этот курс.",
    "tired_mixed": "У вас красивое лицо с сильной природной базой. Главное сейчас — вернуть свежесть взгляду, мягкий тонус и убрать усталость, которая прячет вашу настоящую красоту. Именно для этого создан этот курс.",
}

AGE_CHANGE_STAGES: dict[str, list[tuple[str, str]]] = {
    "muscular": [
        ("25–30", "начинают проявляться мимические линии лба и межбровья"),
        ("30–35", "вертикальные заломы в межбровье могут становиться глубже"),
        ("35–40", "гипертонус жевательных делает нижнюю часть визуально тяжелее"),
        ("после 40", "мимические морщины легче переходят в статичные борозды"),
    ],
    "deformation_edema": [
        ("25–30", "утренняя отечность и одутловатость могут проходить медленнее"),
        ("30–35", "задержка жидкости делает ткани тяжелее"),
        ("35–40", "нижняя треть и овал быстрее теряют четкость"),
        ("после 40", "перерастянутая жидкостью кожа сложнее держит упругость"),
    ],
    "fine_wrinkle": [
        ("25–30", "заметнее сухость и тонкая сетка вокруг глаз"),
        ("30–35", "кожа быстрее теряет эластичность и мягкую опору"),
        ("35–40", "виски, щеки и губы могут терять объем"),
        ("после 40", "без кровотока и питания лицо выглядит суше"),
    ],
    "tired_mixed": [
        ("25–30", "лицо может выглядеть свежим утром, но уставать к вечеру"),
        ("30–35", "заметнее становятся носослезная зона, носогубка и уголки рта"),
        ("35–40", "пастозность и дефицит объемов сильнее дают невыспавшийся вид"),
        ("после 40", "сочетание признаков требует комплексной поддержки"),
    ],
}

AGE_CHANGE_KB_TEXTS: dict[str, str] = {
    "muscular": (
        "25–30: сначала формируются резкие вертикальные морщины в межбровье.\n\n"
        "30–35: проявляются «рубленые» носогубные складки из-за жесткого мышечного зажима.\n\n"
        "После 40: спазм лобной мышцы может давать нависание верхнего века. Сейчас — лучшее время начать."
    ),
    "deformation_edema": (
        "25–30: заметнее утренняя одутловатость, которая частично проходит к вечеру.\n\n"
        "30–35: лишняя жидкость растягивает ткани; под глазами формируются отечные мешки, контуры становятся пастозными.\n\n"
        "После 40: кожа теряет ресурс упругости, овал и нижняя треть тяжелеют. Сейчас — лучшее время начать."
    ),
    "fine_wrinkle": (
        "25–30: заметнее сухость и мелкая сеточка вокруг глаз.\n\n"
        "30–35: лицо начинает терять объемы — первыми проваливаются виски и щеки, губы истончаются.\n\n"
        "После 40–45: кожа сильнее обтягивает костную основу из-за дефицита жировой и мышечной прослойки. Сейчас — лучшее время начать."
    ),
    "tired_mixed": (
        "25–30: лицо свежее утром, но к вечеру быстрее устает.\n\n"
        "30–35: углубляются носослезная борозда и носогубные складки, опускаются уголки рта.\n\n"
        "После 40: пастозность, дефицит объемов и ощущение невыспавшегося лица становятся заметнее. Сейчас — лучшее время начать."
    ),
}

AGE_CHANGE_TYPE_LABELS: dict[str, str] = {
    "muscular": "мускульного типа",
    "deformation_edema": "деформационно-отечного типа",
    "fine_wrinkle": "мелкоморщинистого типа",
    "tired_mixed": "усталого / смешанного типа",
}

AGE_CHANGE_REQUIRED_MARKERS: dict[str, tuple[str, ...]] = {
    "muscular": ("межбров", "лоб", "жеватель", "мимик", "напряж"),
    "deformation_edema": ("отеч", "отёч", "пастоз", "овал", "нижн", "шея", "отток"),
    "fine_wrinkle": ("сух", "сетк", "тонк", "текстур", "объем", "объём", "питани"),
    "tired_mixed": ("глаз", "носогуб", "уголк", "устал", "свеж", "тонус"),
}

AGE_CHANGE_ACTION_MARKERS: tuple[str, ...] = (
    "сейчас",
    "начать",
    "поддерж",
    "лучшее время",
    "время начать",
)


class ProtocolValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ClientV4(BaseModel):
    name: str = ""
    age: int = Field(ge=1, le=110)
    date: str = ""


class ImagesV4(BaseModel):
    face_image_url: str = ""
    face_object_position: str = "50% 42%"


class SkinVisualAgeV4(BaseModel):
    section_number: str = "01"
    title: str = "Биологический возраст кожи"
    passport_age: int = Field(ge=1, le=110)
    visual_age: int = Field(ge=1, le=110)
    age_delta: int
    age_delta_label: str
    text: str

    @model_validator(mode="after")
    def validate_delta(self) -> "SkinVisualAgeV4":
        expected_delta = self.visual_age - self.passport_age
        if self.age_delta != expected_delta:
            raise ValueError(f"age_delta must equal visual_age - passport_age ({expected_delta})")
        expected_label = age_delta_label(expected_delta)
        if self.age_delta_label != expected_label:
            raise ValueError(f"age_delta_label must be '{expected_label}'")
        return self


class TextBulletsBlockV4(BaseModel):
    section_number: str
    title: str
    text: str
    bullets: list[str] = Field(default_factory=list)


class SkinTypeV4(TextBulletsBlockV4):
    type_name: str = ""


class AgingTypeV4(BaseModel):
    section_number: str = "04"
    title: str = "Тип старения"
    type_id: AgingTypeId
    type_name: str
    display_name: str = ""
    confidence: Confidence = "medium"
    evidence: list[str] = Field(default_factory=list)
    combo_type_ids: list[str] = Field(default_factory=list)
    combo_type_names: list[str] = Field(default_factory=list)
    text: str

    @model_validator(mode="after")
    def validate_name(self) -> "AgingTypeV4":
        expected = AGING_TYPE_NAMES[self.type_id]
        if self.type_name != expected:
            raise ValueError(f"aging_type.type_name must be '{expected}'")
        allowed_combo = set(MIXED_COMPONENT_NAMES)
        invalid_combo = [item for item in self.combo_type_ids if item not in allowed_combo]
        if invalid_combo:
            raise ValueError(f"aging_type.combo_type_ids contains unknown components: {invalid_combo}")
        if not self.display_name:
            self.display_name = build_aging_type_display_name(self.type_id, self.combo_type_ids)
        return self


class AgeChangesV4(BaseModel):
    section_number: str = "06"
    title: str = "Первые изменения по возрасту"
    text: str


class ForecastItemV4(BaseModel):
    period: str
    text: str


class TimeForecastV4(BaseModel):
    section_number: str = "08"
    title: str = "Прогноз по времени"
    intro: str = "Если ты начнёшь заниматься по нашей системе:"
    items: list[ForecastItemV4]


class GrowthZonesV4(BaseModel):
    section_number: str = "09"
    title: str = "Зоны роста"
    summary: str
    items: list[str] = Field(default_factory=list)


class ZoneAnchorV4(BaseModel):
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)


class ZoneMapZoneV4(BaseModel):
    id: str
    number: int = Field(ge=1)
    title: str
    status: ZoneStatus
    meaning: str
    anchor: ZoneAnchorV4
    shape: dict[str, Any] = Field(default_factory=dict)


class ZoneMapV4(BaseModel):
    title: str = "Карта зон лица"
    zones: list[ZoneMapZoneV4]


class FinalSummaryV4(BaseModel):
    text: str
    quote: str


class FooterV4(BaseModel):
    disclaimer: str = "Это предварительный визуальный AI-разбор по фото. Не медицинское заключение и не замена консультации специалиста."


class MetaV4(BaseModel):
    main_segment: str = ""
    lead_temperature: str = "warm"
    fallback_used: bool = False


class BellaFaceProtocolV4(BaseModel):
    model_config = ConfigDict(extra="allow")

    protocol_version: Literal["bella_face_protocol_v4"]
    client: ClientV4
    images: ImagesV4 = Field(default_factory=ImagesV4)
    skin_visual_age: SkinVisualAgeV4
    skin_type: SkinTypeV4
    face_strengths: TextBulletsBlockV4
    aging_type: AgingTypeV4
    future_changes: TextBulletsBlockV4
    age_changes: AgeChangesV4
    face_fitness_benefits: TextBulletsBlockV4
    time_forecast: TimeForecastV4
    growth_zones: GrowthZonesV4
    zone_map: ZoneMapV4
    final_summary: FinalSummaryV4
    footer: FooterV4 = Field(default_factory=FooterV4)
    meta: MetaV4 = Field(default_factory=MetaV4)

    @model_validator(mode="after")
    def validate_passport_age(self) -> "BellaFaceProtocolV4":
        if self.skin_visual_age.passport_age != self.client.age:
            raise ValueError("skin_visual_age.passport_age must equal client.age")
        return self


def age_delta_label(delta: int) -> str:
    if delta <= -3:
        return "визуально моложе паспортного возраста"
    if delta >= 3:
        return "чуть старше паспортного возраста"
    return "примерно на свой возраст"


def target_visual_age(passport_age: int, ai_visual_age: Any = None) -> int:
    """Client rule: visual age is passport age plus 2-3 years."""
    try:
        ai_age = int(ai_visual_age)
    except Exception:
        ai_age = passport_age + 2
    delta = ai_age - passport_age
    target_delta = 3 if delta >= 3 else 2
    return max(1, min(110, passport_age + target_delta))


def sync_visual_age_text(text: Any, visual_age: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    visual_pattern = r"визуально\s*[—-]\s*(?:на\s+)?\d{1,3}\s*(?:год|года|лет)"
    if re.search(visual_pattern, value, flags=re.IGNORECASE):
        return re.sub(visual_pattern, f"Визуально — на {visual_age} лет", value, count=1, flags=re.IGNORECASE)
    replacement = f"на {visual_age} лет"
    for pattern in (r"на\s+\d{1,3}\s*(?:год|года|лет)", r"примерно\s+\d{1,3}\s*(?:год|года|лет)"):
        if re.search(pattern, value, flags=re.IGNORECASE):
            return re.sub(pattern, replacement, value, count=1, flags=re.IGNORECASE)
    return value


def _normalize_for_match(text: Any) -> str:
    value = "" if text is None else str(text)
    value = value.replace("ё", "е").replace("Ё", "Е")
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"[^0-9A-Za-zА-Яа-я%/-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def _iter_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        result: list[tuple[str, str]] = []
        for key, item in value.items():
            result.extend(_iter_strings(item, f"{path}.{key}" if path else str(key)))
        return result
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            result.extend(_iter_strings(item, f"{path}[{index}]"))
        return result
    return []


def _all_text(output: dict[str, Any]) -> str:
    return "\n".join(text for _, text in _iter_strings(output))


def _section_text(output: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        value = output.get(key)
        if isinstance(value, dict):
            parts.extend(text for _, text in _iter_strings(value))
    return "\n".join(parts)


def validate_schema(output: dict[str, Any]) -> dict[str, Any]:
    try:
        return BellaFaceProtocolV4.model_validate(output).model_dump()
    except ValidationError as exc:
        raise ProtocolValidationError([f"schema: {err['loc']}: {err['msg']}" for err in exc.errors()]) from exc


def validate_allowed_aging_type(output: dict[str, Any]) -> list[str]:
    aging = output.get("aging_type") if isinstance(output.get("aging_type"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    type_name = str(aging.get("type_name") or "")
    errors: list[str] = []
    if type_id not in AGING_TYPE_NAMES:
        errors.append(f"forbidden aging type_id: {type_id or '<missing>'}")
    elif type_name != AGING_TYPE_NAMES[type_id]:
        errors.append(f"aging type_name mismatch for {type_id}: {type_name}")
    return errors


def validate_no_forbidden_phrases(output: dict[str, Any]) -> list[str]:
    normalized_text = _normalize_for_match(_all_text(output))
    found: list[str] = []
    for phrase in FORBIDDEN_PHRASES:
        if _normalize_for_match(phrase) in normalized_text:
            found.append(f"forbidden phrase: {phrase}")
    return found


def validate_visual_age(output: dict[str, Any]) -> list[str]:
    client = output.get("client") if isinstance(output.get("client"), dict) else {}
    skin_age = output.get("skin_visual_age") if isinstance(output.get("skin_visual_age"), dict) else {}
    errors: list[str] = []
    if not isinstance(skin_age.get("visual_age"), int):
        errors.append("missing visual_age")
        return errors
    if not isinstance(client.get("age"), int):
        errors.append("missing client.age")
        return errors
    passport_age = skin_age.get("passport_age")
    visual_age = skin_age.get("visual_age")
    if passport_age != client.get("age"):
        errors.append("passport_age must equal client.age")
    delta = visual_age - passport_age
    if visual_age != target_visual_age(passport_age, visual_age):
        errors.append("visual_age must be passport_age + 2 or +3")
    if skin_age.get("age_delta") != delta:
        errors.append("age_delta mismatch")
    expected_label = age_delta_label(delta)
    if skin_age.get("age_delta_label") != expected_label:
        errors.append(f"age_delta_label wrong: expected '{expected_label}'")
    return errors


def validate_no_copied_examples(output: dict[str, Any]) -> list[str]:
    text = _all_text(output)
    normalized_text = _normalize_for_match(text)
    errors: list[str] = []
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+|;", text)
        if len(sentence.strip()) >= 16
    ]
    normalized_sentences = [_normalize_for_match(sentence) for sentence in sentences]
    for phrase in COPIED_EXAMPLE_PHRASES:
        normalized_phrase = _normalize_for_match(phrase)
        if normalized_phrase in normalized_text:
            errors.append(f"copied example phrase: {phrase}")
            continue
        for sentence in normalized_sentences:
            if not sentence:
                continue
            ratio = SequenceMatcher(None, normalized_phrase, sentence).ratio()
            if ratio >= 0.92:
                errors.append(f"near copied example phrase: {phrase}")
                break
    return errors


def validate_no_generic_template_text(output: dict[str, Any]) -> list[str]:
    meta = output.get("meta") if isinstance(output.get("meta"), dict) else {}
    if meta.get("fallback_used") is True:
        return []
    normalized_text = _normalize_for_match(_all_text(output))
    errors: list[str] = []
    for phrase in GENERIC_TEMPLATE_PHRASES:
        if _normalize_for_match(phrase) in normalized_text:
            errors.append(f"generic template phrase: {phrase}")
    return errors


def validate_photo_specific_protocol(output: dict[str, Any]) -> list[str]:
    meta = output.get("meta") if isinstance(output.get("meta"), dict) else {}
    if meta.get("fallback_used") is True:
        return []
    markers = _photo_specific_markers(output)
    if len(markers) < 2:
        return ["photo-specific markers missing: evidence or zone details required"]
    required_blocks = (
        "skin_visual_age",
        "skin_type",
        "face_strengths",
        "aging_type",
        "future_changes",
        "age_changes",
        "face_fitness_benefits",
        "time_forecast",
        "final_summary",
    )
    matched = [
        key
        for key in required_blocks
        if _has_photo_specific_marker(_block_text_from(output, key), output)
        or _has_observable_block_detail(key, _block_text_from(output, key), output)
    ]
    if len(matched) < len(required_blocks):
        missing = ", ".join(key for key in required_blocks if key not in matched)
        return [f"photo-specific text too generic: add current photo markers to every visible block; missing {missing}"]
    return []


def _has_observable_block_detail(key: str, text: Any, output: dict[str, Any]) -> bool:
    """Accept photo-specific writing even when the AI paraphrases zone markers."""
    normalized = _normalize_for_match(text)
    if not normalized:
        return False

    aging = output.get("aging_type") if isinstance(output.get("aging_type"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    type_markers = TYPE_MARKERS.get(type_id, ())
    mixed_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    if mixed_components:
        component_markers: list[str] = []
        for component_id in mixed_components:
            component_markers.extend(MIXED_COMPONENT_MARKERS.get(component_id, ()))
        type_markers = tuple(dict.fromkeys([*type_markers, *component_markers]))

    observable_markers = (
        "кожа",
        "тон",
        "текстур",
        "светл",
        "румян",
        "краснот",
        "глаз",
        "взгляд",
        "бров",
        "век",
        "нос",
        "крыл",
        "ще",
        "скул",
        "губ",
        "подбород",
        "овал",
        "нижн",
        "носогуб",
        "носослез",
        "носослёз",
        "симметр",
        "пропорц",
        "форма",
        "контур",
    )

    if key == "skin_visual_age":
        visual_age = ""
        block = output.get("skin_visual_age") if isinstance(output.get("skin_visual_age"), dict) else {}
        if isinstance(block.get("visual_age"), int):
            visual_age = str(block["visual_age"])
        has_age = bool(visual_age and visual_age in normalized) or "визуаль" in normalized
        return has_age and _marker_count(normalized, observable_markers) >= 2

    if key == "skin_type":
        skin_markers = (*SKIN_POSITIVE_MARKERS, *SKIN_FEATURE_MARKERS, *SKIN_POTENTIAL_MARKERS)
        return _marker_count(normalized, skin_markers) >= 3 and _marker_count(normalized, observable_markers) >= 1

    if key == "face_strengths":
        covered = 0
        for markers in FACE_STRENGTH_MARKERS.values():
            if any(marker in normalized for marker in markers):
                covered += 1
        return covered >= 4

    if key in {"aging_type", "future_changes", "age_changes", "face_fitness_benefits", "time_forecast", "final_summary"}:
        has_type_logic = _marker_count(normalized, type_markers) >= 2
        has_observable = _marker_count(normalized, observable_markers) >= 1
        if key in {"time_forecast", "final_summary"}:
            return has_type_logic or (has_observable and _marker_count(normalized, type_markers) >= 1)
        return has_type_logic and has_observable

    return False


def _marker_count(text: str, markers: tuple[str, ...]) -> int:
    return sum(1 for marker in markers if re.search(re.escape(marker), text, flags=re.IGNORECASE))


def _component_type_id(component_id: str) -> str:
    return "tired_mixed" if component_id == "tired" else component_id


def _combo_marker_sets(
    component_ids: list[str] | None,
    marker_map: dict[str, tuple[str, ...]],
) -> list[tuple[str, tuple[str, ...]]]:
    result: list[tuple[str, tuple[str, ...]]] = []
    for component_id in _unique_mixed_components(component_ids or [])[:2]:
        type_id = _component_type_id(component_id)
        markers = marker_map.get(type_id)
        if markers:
            result.append((component_id, markers))
    return result


def _combo_marker_count(
    text: str,
    component_ids: list[str] | None,
    marker_map: dict[str, tuple[str, ...]],
) -> int:
    seen: set[str] = set()
    total = 0
    for _, markers in _combo_marker_sets(component_ids, marker_map):
        for marker in markers:
            if marker in seen:
                continue
            seen.add(marker)
            if re.search(re.escape(marker), text, flags=re.IGNORECASE):
                total += 1
    return total


def _normalize_mixed_component_id(value: Any) -> str | None:
    text = _normalize_for_match(value)
    if not text:
        return None
    if text in MIXED_COMPONENT_NAMES:
        return text
    for marker, component_id in MIXED_COMPONENT_ALIASES.items():
        if marker in text:
            return component_id
    return None


def _mixed_component_names(component_ids: list[str]) -> list[str]:
    return [MIXED_COMPONENT_NAMES[item] for item in component_ids if item in MIXED_COMPONENT_NAMES]


def build_aging_type_display_name(type_id: str, mixed_components: list[str] | None = None) -> str:
    if type_id == "tired_mixed" and mixed_components:
        components = _unique_mixed_components(mixed_components)
        if len(components) > 1:
            return f"Комбинированный: {' + '.join(_mixed_component_names(components))}"
    return AGING_TYPE_NAMES.get(type_id, AGING_TYPE_NAMES["tired_mixed"])


def _unique_mixed_components(component_ids: list[str]) -> list[str]:
    result: list[str] = []
    for component_id in component_ids:
        normalized = _normalize_mixed_component_id(component_id)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def mixed_combo_type_ids_from_payload(payload: dict[str, Any] | None) -> list[str]:
    source = payload if isinstance(payload, dict) else {}
    aging = source.get("aging_type") if isinstance(source.get("aging_type"), dict) else {}
    explicit_sources = [
        aging.get("combo_type_ids"),
        aging.get("combo_components"),
        aging.get("combo_type_names"),
        aging.get("mixed_components"),
        aging.get("display_name"),
        aging.get("combined_label"),
    ]
    explicit: list[str] = []
    for items in explicit_sources:
        if isinstance(items, list):
            explicit.extend(str(item) for item in items)
        elif isinstance(items, str):
            explicit.extend(re.split(r"[,/+]+|\s+и\s+", items))
    explicit_components = _unique_mixed_components(explicit)
    if explicit_components:
        return explicit_components[:2]

    def collect_focus_text(data: Any) -> list[str]:
        if not isinstance(data, dict):
            return []
        result: list[str] = []
        for key in ("aging_type", "aging_profile", "face_type", "face_aging", "face_and_aging_type", "aging_type_block"):
            block = data.get(key)
            if isinstance(block, dict):
                for field in (
                    "type_id",
                    "type_name",
                    "display_name",
                    "combined_label",
                    "aging_type",
                    "text",
                    "description",
                    "main_scenario",
                    "evidence",
                    "evidence_from_photo",
                    "what_appears_first",
                    "recommended_start",
                    "base_note",
                ):
                    value = block.get(field)
                    if isinstance(value, list):
                        result.extend(str(item) for item in value)
                    elif value:
                        result.append(str(value))
            elif block:
                result.append(str(block))
        context = data.get("analysis_context")
        if isinstance(context, dict):
            result.extend(str(value) for key, value in context.items() if "aging" in str(key) and value)
        strict_blocks = data.get("strict_blocks")
        if isinstance(strict_blocks, dict):
            result.extend(collect_focus_text({"aging_type": strict_blocks.get("aging_type")}))
        journal = data.get("journal_protocol")
        if isinstance(journal, dict):
            result.extend(collect_focus_text({"face_type": journal.get("face_type")}))
        for nested_key in ("protocol_copy", "analysis_json", "analysis", "personal_insight"):
            nested = data.get(nested_key)
            if isinstance(nested, dict):
                result.extend(collect_focus_text(nested))
        for zones_key in ("zones",):
            zones = data.get(zones_key)
            if isinstance(zones, list):
                for zone in zones:
                    if isinstance(zone, dict):
                        result.extend(
                            str(zone.get(field))
                            for field in ("title", "name", "meaning", "description", "what_is_visible", "why_it_matters")
                            if zone.get(field)
                        )
        zone_map = data.get("zone_map")
        if isinstance(zone_map, dict):
            result.extend(collect_focus_text({"zones": zone_map.get("zones")}))
        return result

    text = _normalize_for_match("\n".join(collect_focus_text(source)))
    scores = {
        component_id: _marker_count(text, markers)
        for component_id, markers in MIXED_COMPONENT_MARKERS.items()
    }
    scored_components = [item for item, score in sorted(scores.items(), key=lambda pair: pair[1], reverse=True) if score > 0]
    if not scored_components:
        return ["tired"]
    return scored_components[:2]


def _build_mixed_aging_type_text(component_ids: list[str]) -> str:
    components = _unique_mixed_components(component_ids)
    if not components:
        return AGING_TYPE_TEXTS["tired_mixed"]
    if len(components) == 1:
        component = components[0]
        return AGING_TYPE_TEXTS["tired_mixed"] if component == "tired" else AGING_TYPE_TEXTS.get(component, AGING_TYPE_TEXTS["tired_mixed"])
    components = components[:2]
    names = _mixed_component_names(components)
    characteristic_parts = [MIXED_COMPONENT_CHARACTERISTICS[item] for item in components if item in MIXED_COMPONENT_CHARACTERISTICS]
    return _clip_text(
        (
            f"Комбинированный сценарий: {' + '.join(names)}.\n\n"
            f"{'. '.join(part[:1].upper() + part[1:] for part in characteristic_parts)}. "
            "Формат работы строится не по одному признаку, а по сочетанию этих механизмов."
        ),
        TEXT_LIMITS["aging_type.text"],
    )


def _build_mixed_future_changes_text(component_ids: list[str]) -> str:
    components = _unique_mixed_components(component_ids)
    if not components:
        return FUTURE_CHANGE_TEXTS["tired_mixed"]
    if len(components) == 1:
        component = components[0]
        return FUTURE_CHANGE_TEXTS["tired_mixed"] if component == "tired" else FUTURE_CHANGE_TEXTS.get(component, FUTURE_CHANGE_TEXTS["tired_mixed"])
    primary, secondary = components[:2]
    primary_text = MIXED_FUTURE_COMPONENT_TEXTS.get(primary, "")
    secondary_text = MIXED_FUTURE_COMPONENT_TEXTS.get(secondary, "")
    primary_name = MIXED_COMPONENT_NAMES.get(primary, "первый").lower()
    secondary_name = MIXED_COMPONENT_NAMES.get(secondary, "второй").lower()
    text = (
        "Как меняется лицо со временем\n\n"
        f"Без грамотного ухода и поддержки комбинированного сценария сначала может сильнее проявляться {primary_name} сценарий: "
        f"{primary_text}. Параллельно подключается {secondary_name} сценарий: {secondary_text}."
    )
    return _clip_text(text, TEXT_LIMITS["future_changes.text"])


def _build_mixed_age_changes_text(component_ids: list[str], passport_age: int | None) -> str:
    components = _unique_mixed_components(component_ids)
    if len(components) < 2:
        return ""
    primary, secondary = components[:2]
    primary_name = MIXED_COMPONENT_NAMES.get(primary, "первый").lower()
    secondary_name = MIXED_COMPONENT_NAMES.get(secondary, "второй").lower()
    primary_text = MIXED_AGE_COMPONENT_TEXTS.get(primary, "")
    secondary_text = MIXED_AGE_COMPONENT_TEXTS.get(secondary, "")
    return (
        f"25–30: обычно первым проявляется {primary_name} сценарий — {primary_text}.\n\n"
        f"30–35: подключается {secondary_name} сценарий — {secondary_text}.\n\n"
        "После 40: оба механизма могут сильнее влиять на выражение лица и качество тканей. Сейчас — лучшее время начать."
    )


def validate_aging_consistency(output: dict[str, Any]) -> list[str]:
    aging = output.get("aging_type") if isinstance(output.get("aging_type"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    if type_id not in AGING_TYPE_NAMES:
        return [f"inconsistent aging type: {type_id or '<missing>'}"]

    key_text = _normalize_for_match(
        _section_text(
            output,
            "aging_type",
            "future_changes",
            "age_changes",
            "face_fitness_benefits",
            "time_forecast",
            "growth_zones",
            "final_summary",
        )
    )
    errors: list[str] = []
    allowed_combo_ids = set()
    combo_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    if type_id == "tired_mixed":
        allowed_combo_ids = {_component_type_id(item) for item in combo_components}
    if type_id == "tired_mixed" and len(combo_components) > 1:
        own_count = _combo_marker_count(key_text, combo_components, TYPE_MARKERS)
        missing_components = [
            MIXED_COMPONENT_NAMES.get(component_id, component_id)
            for component_id, markers in _combo_marker_sets(combo_components, TYPE_MARKERS)
            if _marker_count(key_text, markers) == 0
        ]
        if missing_components:
            errors.append("inconsistent aging type: combo text missing markers for " + ", ".join(missing_components))
    else:
        own_count = _marker_count(key_text, TYPE_MARKERS[type_id])
        if own_count == 0:
            errors.append(f"inconsistent aging type: text has no markers for {type_id}")

    for other_id, markers in TYPE_MARKERS.items():
        if other_id == type_id:
            continue
        if other_id in allowed_combo_ids:
            continue
        other_count = _marker_count(key_text, markers)
        strong_count = sum(
            1 for pattern in STRONG_FOREIGN_PATTERNS[other_id] if re.search(pattern, key_text, flags=re.IGNORECASE)
        )
        if strong_count >= 2 and other_count >= own_count:
            errors.append(f"inconsistent aging type: text drifts toward {other_id}")
        elif own_count == 0 and other_count >= 2:
            errors.append(f"inconsistent aging type: text uses {other_id} markers instead of {type_id}")
    return errors


def validate_face_strengths_concrete(output: dict[str, Any]) -> list[str]:
    block = output.get("face_strengths") if isinstance(output.get("face_strengths"), dict) else {}
    text = _normalize_for_match(
        " ".join(
            [
                str(block.get("text") or ""),
                " ".join(str(item) for item in block.get("bullets", []) if item),
            ]
        )
    )
    if not text:
        return ["face_strengths missing"]
    errors: list[str] = []
    for label, markers in FACE_STRENGTH_MARKERS.items():
        if label == "природный актив / эффект процедур":
            # This sales nuance is repaired in enforce_protocol_v4_writing_format.
            # Do not discard an otherwise photo-specific AI analysis only for this phrase.
            continue
        if not any(marker in text for marker in markers):
            errors.append(f"face_strengths missing concrete compliment: {label}")
    return errors


def normalize_skin_type_name(value: Any) -> str:
    text = _normalize_for_match(value)
    if not text or text in {"normal", "unknown", "none"} or "норм" in text:
        return "Комбинированная, с ровной плотной базой"
    if "чувств" in text or "реактив" in text or "sensitive" in text:
        return "Чувствительная, реактивная"
    if "t-зон" in text or "t зон" in text or "т-зон" in text or "т зон" in text or "жир" in text or "себум" in text or "oily" in text:
        return "Комбинированная, активная в T-зоне"
    if "сух" in text and "комби" not in text:
        return "Сухая, склонная к обезвоженности"
    if "обезвож" in text or "комби" in text or "combination" in text or "mixed" in text:
        if "ровн" in text or "плот" in text:
            return "Комбинированная, с ровной плотной базой"
        return "Комбинированная, склонная к обезвоженности"
    return "Комбинированная, с ровной плотной базой"


def _skin_type_key(type_name: Any) -> str:
    normalized = normalize_skin_type_name(type_name)
    if normalized == "Сухая, склонная к обезвоженности":
        return "dry_dehydrated"
    if normalized == "Комбинированная, активная в T-зоне":
        return "combination_tzone"
    if normalized == "Чувствительная, реактивная":
        return "sensitive_reactive"
    if normalized == "Комбинированная, с ровной плотной базой":
        return "combination_dense"
    return "combination_dehydrated"


def build_skin_type_text(type_name: Any) -> str:
    return _clip_text(SKIN_TYPE_TEXTS[_skin_type_key(type_name)], TEXT_LIMITS["skin_type.text"])


def build_skin_type_bullets(type_name: Any) -> list[str]:
    key = _skin_type_key(type_name)
    bullets = {
        "dry_dehydrated": ["Плюс: мягкий ровный тон.", "Фокус: питание и увлажнение."],
        "combination_tzone": ["Плюс: плотность и ресурс.", "Фокус: баланс T-зоны и влага."],
        "sensitive_reactive": ["Плюс: быстрый ответ на бережность.", "Фокус: восстановление барьера."],
        "combination_dense": ["Плюс: кожа держит каркас.", "Фокус: увлажнение зоны глаз."],
        "combination_dehydrated": ["Плюс: кожа держит каркас.", "Фокус: влага и ровное сияние."],
    }[key]
    return bullets[: LIST_LIMITS["skin_type.bullets"]]


def is_skin_type_text_valid(text: Any) -> bool:
    normalized = _normalize_for_match(text)
    if not normalized:
        return False
    if "glass skin" in normalized:
        return False
    if not any(marker in normalized for marker in ("комби", "сух", "чувств", "t-зон", "t зон", "т-зон", "т зон", "обезвож", "плотн")):
        return False
    if "плюс" not in normalized:
        return False
    if not any(marker in normalized for marker in SKIN_FEATURE_MARKERS):
        return False
    return any(marker in normalized for marker in SKIN_POTENTIAL_MARKERS)


def validate_skin_type_structure(output: dict[str, Any]) -> list[str]:
    block = output.get("skin_type") if isinstance(output.get("skin_type"), dict) else {}
    text = " ".join(
        [
            str(block.get("type_name") or ""),
            str(block.get("text") or ""),
            " ".join(str(item) for item in block.get("bullets", []) if item),
        ]
    )
    if not is_skin_type_text_valid(text):
        return ["skin_type must follow structure: type + positive base + feature/need + potential"]
    return []


def validate_future_changes_from_knowledge(output: dict[str, Any]) -> list[str]:
    aging = output.get("aging_type") if isinstance(output.get("aging_type"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    block = output.get("future_changes") if isinstance(output.get("future_changes"), dict) else {}
    text = _normalize_for_match(
        " ".join(
            [
                str(block.get("text") or ""),
                " ".join(str(item) for item in block.get("bullets", []) if item),
            ]
        )
    )
    if not text:
        return ["future_changes missing"]
    errors: list[str] = []
    if not any(marker in text for marker in FUTURE_SUPPORT_MARKERS):
        errors.append("future_changes must explain what may happen without regular care/support")
    combo_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    if type_id == "tired_mixed" and len(combo_components) > 1:
        missing_components = [
            MIXED_COMPONENT_NAMES.get(component_id, component_id)
            for component_id, markers in _combo_marker_sets(combo_components, FUTURE_CHANGE_MARKERS)
            if _marker_count(text, markers) == 0
        ]
        if missing_components:
            errors.append("future_changes missing knowledge-base markers for combo components: " + ", ".join(missing_components))
    elif type_id not in FUTURE_CHANGE_MARKERS:
        errors.append(f"future_changes unknown aging type: {type_id or '<missing>'}")
    elif _marker_count(text, FUTURE_CHANGE_MARKERS[type_id]) < 2:
        errors.append(f"future_changes missing knowledge-base markers for {type_id}")
    for word in FUTURE_FEAR_WORDS:
        if word in text:
            errors.append(f"future_changes uses fear wording: {word}")
    return errors


def is_future_changes_text_valid(text: Any, type_id: str, mixed_components: list[str] | None = None) -> bool:
    normalized = _normalize_for_match(text)
    if not normalized or type_id not in FUTURE_CHANGE_MARKERS:
        return False
    if not any(marker in normalized for marker in FUTURE_SUPPORT_MARKERS):
        return False
    if type_id == "tired_mixed" and mixed_components and len(_unique_mixed_components(mixed_components)) > 1:
        if not all(_marker_count(normalized, markers) > 0 for _, markers in _combo_marker_sets(mixed_components, FUTURE_CHANGE_MARKERS)):
            return False
        return not any(word in normalized for word in FUTURE_FEAR_WORDS)
    if _marker_count(normalized, FUTURE_CHANGE_MARKERS[type_id]) < 2:
        return False
    return not any(word in normalized for word in FUTURE_FEAR_WORDS)


def build_future_changes_text(type_id: str, mixed_components: list[str] | None = None) -> str:
    if type_id == "tired_mixed" and mixed_components:
        text = _build_mixed_future_changes_text(mixed_components)
        return _clip_text(text, TEXT_LIMITS["future_changes.text"])
    text = FUTURE_CHANGE_TEXTS.get(type_id, FUTURE_CHANGE_TEXTS["tired_mixed"])
    return _clip_text(text, TEXT_LIMITS["future_changes.text"])


def build_aging_type_text(type_id: str, mixed_components: list[str] | None = None) -> str:
    if type_id == "tired_mixed" and mixed_components:
        text = _build_mixed_aging_type_text(mixed_components)
        return _clip_text(text, TEXT_LIMITS["aging_type.text"])
    return _clip_text(AGING_TYPE_TEXTS.get(type_id, AGING_TYPE_TEXTS["tired_mixed"]), TEXT_LIMITS["aging_type.text"])


def build_face_strengths_text(type_id: str) -> str:
    return _clip_text(FACE_STRENGTH_TEXTS.get(type_id, FACE_STRENGTH_TEXTS["tired_mixed"]), TEXT_LIMITS["face_strengths.text"])


def build_face_strengths_bullets(type_id: str) -> list[str]:
    return FACE_STRENGTH_BULLETS.get(type_id, FACE_STRENGTH_BULLETS["tired_mixed"])[: LIST_LIMITS["face_strengths.bullets"]]


def build_face_fitness_benefits_text(type_id: str) -> str:
    return _clip_text(
        FACE_FITNESS_BENEFIT_TEXTS.get(type_id, FACE_FITNESS_BENEFIT_TEXTS["tired_mixed"]),
        TEXT_LIMITS["face_fitness_benefits.text"],
    )


def build_face_fitness_benefits_bullets(type_id: str) -> list[str]:
    return FACE_FITNESS_BENEFIT_BULLETS.get(type_id, FACE_FITNESS_BENEFIT_BULLETS["tired_mixed"])[
        : LIST_LIMITS["face_fitness_benefits.bullets"]
    ]


def build_final_summary_text(type_id: str) -> str:
    return _clip_text(FINAL_SUMMARY_TEXTS.get(type_id, FINAL_SUMMARY_TEXTS["tired_mixed"]), TEXT_LIMITS["final_summary.text"])


def _age_stage_index(age: int) -> int:
    if age < 30:
        return 0
    if age < 35:
        return 1
    if age < 40:
        return 2
    return 3


def _age_marker_variants(marker: str) -> tuple[str, ...]:
    normalized = _normalize_for_match(marker)
    if normalized.startswith("после "):
        value = normalized.removeprefix("после ").strip()
        return (normalized, value)
    return (normalized, f"{normalized} лет")


def _expected_age_markers(age: int) -> tuple[str, ...]:
    idx = _age_stage_index(age)
    markers = ("25–30", "30–35", "35–40", "после 40")
    nearby = markers[max(0, idx - 1) : min(len(markers), idx + 2)]
    variants: list[str] = []
    for marker in nearby:
        variants.extend(_age_marker_variants(marker))
    return tuple(variants)


def _format_age_stage(marker: str, text: str, *, first: bool = False) -> str:
    if first:
        return f"в {marker} лет обычно {text}" if not marker.startswith("после") else f"{marker} обычно {text}"
    if marker.startswith("после"):
        return f"{marker.capitalize()} {text}."
    return f"В {marker} — {text}."


def build_age_changes_text(type_id: str, passport_age: int | None, mixed_components: list[str] | None = None) -> str:
    if type_id == "tired_mixed" and mixed_components:
        mixed_text = _build_mixed_age_changes_text(mixed_components, passport_age)
        if mixed_text:
            return _clip_text(mixed_text, TEXT_LIMITS["age_changes.text"])
    kb_text = AGE_CHANGE_KB_TEXTS.get(type_id)
    if kb_text:
        return _clip_text(kb_text, TEXT_LIMITS["age_changes.text"])
    stages = AGE_CHANGE_STAGES.get(type_id, AGE_CHANGE_STAGES["tired_mixed"])
    idx = _age_stage_index(passport_age or 30)
    selected = stages[idx : idx + 2]
    if len(selected) < 2:
        selected = stages[-2:]
    later_marker, later_text = stages[-1]
    if selected[-1][0] == later_marker:
        later_sentence = ""
    else:
        later_sentence = f" {later_marker.capitalize()} {later_text}."
    first_marker, first_text = selected[0]
    second_marker, second_text = selected[1]
    text = (
        f"Для вашего типа старения {_format_age_stage(first_marker, first_text, first=True)}. "
        f"{_format_age_stage(second_marker, second_text)}"
        f"{later_sentence} Сейчас — лучшее время начать."
    )
    if len(text) > TEXT_LIMITS["age_changes.text"]:
        text = (
            f"Для вашего типа старения {_format_age_stage(first_marker, first_text, first=True)}. "
            f"{_format_age_stage(second_marker, second_text)}"
            " Сейчас — лучшее время начать."
        )
    return _clip_text(text, TEXT_LIMITS["age_changes.text"])


PHOTO_CONTEXT_ZONE_FIELDS: tuple[str, ...] = (
    "what_is_visible",
    "meaning",
    "description",
    "reason",
    "short_comment",
    "why_it_matters",
)

PHOTO_CONTEXT_EVIDENCE_FIELDS: tuple[str, ...] = (
    "evidence",
    "evidence_from_photo",
    "what_appears_first",
    "visible_signs",
    "features",
    "strengths",
)

PHOTO_CONTEXT_NESTED_KEYS: tuple[str, ...] = (
    "analysis",
    "analysis_json",
    "protocol_copy",
    "personal_insight",
    "journal_protocol",
    "strict_blocks",
    "bella_protocol_v4",
)

PHOTO_CONTEXT_EMPTY_MARKERS: tuple[str, ...] = (
    "визуально не определено",
    "не определено",
    "данные отсутствуют",
    "unknown",
    "none",
)

PHOTO_SPECIFIC_BLOCKS: tuple[str, ...] = (
    "skin_visual_age",
    "skin_type",
    "face_strengths",
    "aging_type",
    "future_changes",
    "age_changes",
    "face_fitness_benefits",
    "final_summary",
)


def _sanitize_photo_context_text(value: Any, max_chars: int = 92) -> str:
    text = re.sub(r"[*_`#>]+", "", str(value or ""))
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    text = re.sub(r"\s+", " ", text).strip(" .,:;—–-")
    if not text:
        return ""
    normalized = _normalize_for_match(text)
    if any(marker in normalized for marker in PHOTO_CONTEXT_EMPTY_MARKERS):
        return ""
    return _clip_text(text, max_chars).rstrip(".")


def _iter_photo_zone_blocks(payload: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 3 or not isinstance(payload, dict):
        return []
    blocks: list[dict[str, Any]] = []
    for key in ("zones",):
        zones = payload.get(key)
        if isinstance(zones, list):
            blocks.extend(zone for zone in zones if isinstance(zone, dict))
    zone_map = payload.get("zone_map")
    if isinstance(zone_map, dict):
        zones = zone_map.get("zones")
        if isinstance(zones, list):
            blocks.extend(zone for zone in zones if isinstance(zone, dict))
    for key in PHOTO_CONTEXT_NESTED_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            blocks.extend(_iter_photo_zone_blocks(nested, depth + 1))
    return blocks


def _photo_zone_context_items(payload: dict[str, Any] | None, limit: int = 3) -> list[tuple[str, str]]:
    source = payload if isinstance(payload, dict) else {}
    zones = _iter_photo_zone_blocks(source)
    if not zones:
        return []

    scored: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()
    priority = {"red": 0, "orange": 1, "yellow": 2, "green": 3}
    for index, zone in enumerate(zones):
        title = _sanitize_photo_context_text(zone.get("title") or zone.get("name") or zone.get("label"), 44)
        if not title:
            continue
        normalized_title = _normalize_for_match(title)
        if normalized_title in seen:
            continue
        note = ""
        for field in PHOTO_CONTEXT_ZONE_FIELDS:
            note = _sanitize_photo_context_text(zone.get(field), 96)
            if note and _normalize_for_match(note) != normalized_title:
                break
        if not note:
            continue
        seen.add(normalized_title)
        status = _normalize_for_match(zone.get("status"))
        scored.append((priority.get(status, 2), index, title, note))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [(title, note) for _, _, title, note in scored[:limit]]


def _photo_evidence_context_items(payload: Any, limit: int = 3, depth: int = 0) -> list[str]:
    if depth > 3 or not isinstance(payload, dict):
        return []
    items: list[str] = []
    for field in PHOTO_CONTEXT_EVIDENCE_FIELDS:
        value = payload.get(field)
        values = value if isinstance(value, list) else [value] if value else []
        for item in values:
            if isinstance(item, dict):
                for nested_field in ("title", "text", "description", "why_it_is_strength", "meaning", "reason"):
                    text = _sanitize_photo_context_text(item.get(nested_field), 88)
                    if text:
                        items.append(text)
                        break
            else:
                text = _sanitize_photo_context_text(item, 88)
                if text:
                    items.append(text)
    for key in ("aging_type", "aging_classification", "face_strengths", "skin_visual_age"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            items.extend(_photo_evidence_context_items(nested, limit, depth + 1))
    for key in PHOTO_CONTEXT_NESTED_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            items.extend(_photo_evidence_context_items(nested, limit, depth + 1))

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = _normalize_for_match(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _format_photo_context_parts(items: list[tuple[str, str]], max_items: int = 2) -> str:
    parts: list[str] = []
    for title, note in items[:max_items]:
        title_text = title[:1].lower() + title[1:]
        note_text = note[:1].lower() + note[1:] if note else ""
        note_text = re.sub(r"^зона,\s*", "", note_text, flags=re.IGNORECASE)
        note_text = re.sub(r"требующ(ая|ий|ее)\s+внимания\s+для", "просит", note_text, flags=re.IGNORECASE)
        note_text = _clip_text(note_text, 72).rstrip(".") if note_text else ""
        if note_text and _normalize_for_match(title_text) in _normalize_for_match(note_text):
            parts.append(note_text)
        else:
            parts.append(f"{title_text} — {note_text}" if note_text else title_text)
    return "; ".join(parts)


def _photo_context_sentence(payload: dict[str, Any] | None, variant: str) -> str:
    source = payload if isinstance(payload, dict) else {}
    zone_items = _photo_zone_context_items(source)
    if zone_items:
        titles = ", ".join(title[:1].lower() + title[1:] for title, _ in zone_items[:2])
        parts = _format_photo_context_parts(zone_items)
        if variant == "future":
            return _clip_text(f"На твоем фото эта динамика читается через: {parts}.", 132)
        if variant == "age":
            return _clip_text(f"Сейчас первыми зонами внимания выглядят {titles}; с них и стоит начать мягкую работу.", 128)
        return _clip_text(f"По фото ведущие маркеры: {parts}.", 132)

    evidence = _photo_evidence_context_items(source, 2)
    if not evidence:
        return ""
    joined = "; ".join(item[:1].lower() + item[1:] for item in evidence)
    if variant == "future":
        return _clip_text(f"На твоем фото это связано с видимыми признаками: {joined}.", 128)
    if variant == "age":
        return _clip_text(f"Сейчас первые зоны внимания по фото: {joined}.", 118)
    return _clip_text(f"По фото выделяются: {joined}.", 122)


def _append_photo_context(base_text: str, note: str, max_chars: int) -> str:
    base = _clip_text(base_text, max_chars)
    note = _sanitize_photo_context_text(note, 150)
    if not note:
        return base
    if _normalize_for_match(note) in _normalize_for_match(base):
        return base
    available = max_chars - len(base) - 2
    if available < 58:
        return base
    return f"{base}\n\n{_clip_text(note, available)}"


def _append_context_preserving_format(base_text: str, note: str, max_chars: int) -> str:
    base = re.sub(r"\s+", " ", str(base_text or "")).strip()
    note = _sanitize_photo_context_text(note, 150)
    if not base:
        return _clip_text(note, max_chars)
    if not note or _normalize_for_match(note) in _normalize_for_match(base):
        return _clip_text(base, max_chars)
    available = max_chars - len(note) - 2
    if available < 90:
        return _clip_text(base, max_chars)
    base_part = _clip_text(base, available).rstrip(".")
    return f"{base_part}.\n\n{note}."


def _restore_age_change_paragraphs(text: Any) -> str:
    value = re.sub(r"[ \t\r\f\v]+", " ", str(text or "")).strip()
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\s+(30\s*[–-]\s*35\s*:)", r"\n\n\1", value)
    value = re.sub(r"\s+(35\s*[–-]\s*40\s*:)", r"\n\n\1", value)
    value = re.sub(r"\s+((?:После|после)\s+40(?:\s*[–-]\s*45)?\s*:)", r"\n\n\1", value)
    value = re.sub(r"\n{2,}(Сейчас\s+[—-])", r" \1", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _format_age_changes_with_photo_context(base_text: str, note: str, output: dict[str, Any], max_chars: int) -> str:
    base = _restore_age_change_paragraphs(base_text)
    focus = _photo_context_focus(output, "")
    if focus:
        photo_sentence = f"Сейчас — лучшее время начать: по фото первыми зонами выглядят {focus}."
        base = re.sub(
            r"Сейчас\s+[—-]\s+лучшее\s+время\s+начать(?:[:.]\s*[^.\n]*)?\.?",
            photo_sentence,
            base,
            flags=re.IGNORECASE,
        )
    else:
        note = _sanitize_photo_context_text(note, 110)
        if note and _normalize_for_match(note) not in _normalize_for_match(base):
            base = f"{base}\n\n{note}."
    if len(base) <= max_chars:
        return base
    paragraphs = [part.strip() for part in base.split("\n\n") if part.strip()]
    if len(paragraphs) >= 3:
        first = _clip_text(paragraphs[0], 112)
        second = _clip_text(paragraphs[1], 132)
        third = paragraphs[2]
        action = f"Сейчас — лучшее время начать: по фото фокус — {focus}." if focus else "Сейчас — лучшее время начать."
        third = re.sub(r"\s*Сейчас\s+[—-]\s+.*$", "", third, flags=re.IGNORECASE).strip()
        remaining = max_chars - len(first) - len(second) - len(action) - 8
        third = _clip_text(third, max(96, remaining)).rstrip(".")
        compact = f"{first}\n\n{second}\n\n{third}. {action}"
        if len(compact) <= max_chars:
            return compact
        action = "Сейчас — лучшее время начать."
        remaining = max_chars - len(first) - len(second) - len(action) - 8
        third = _clip_text(third, max(80, remaining)).rstrip(".")
        return f"{first}\n\n{second}\n\n{third}. {action}"
    selected: list[str] = []
    for paragraph in paragraphs:
        candidate = "\n\n".join([*selected, paragraph])
        if len(candidate) > max_chars:
            break
        selected.append(paragraph)
    if selected:
        return "\n\n".join(selected)
    return _clip_text(base, max_chars)


def _strip_short_type_intro(text: Any, type_name: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", value) if item.strip()]
    if len(sentences) < 2:
        return value
    first = _normalize_for_match(sentences[0])
    type_marker = _normalize_for_match(type_name).split("/")[0].strip()
    if "тип" in first and (type_marker in first or "старени" in first) and len(sentences[0]) <= 95:
        return " ".join(sentences[1:]).strip()
    return value


def _strip_known_block_label(text: str, labels: tuple[str, ...]) -> str:
    value = str(text or "").strip()
    for label in labels:
        pattern = rf"^\s*{re.escape(label)}\s*[:.\n-]*\s*"
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    return value.strip()


def _with_block_label(label: str, text: str, max_chars: int) -> str:
    body = _strip_known_block_label(text, (label,))
    if not body:
        return _clip_text(label, max_chars)
    body = body[:1].lower() + body[1:] if body[:1].isupper() else body
    return _clip_text(f"{label}: {body}", max_chars)


def _photo_specific_markers(output: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    markers.extend(_photo_evidence_context_items(output, 8))
    for title, note in _photo_zone_context_items(output, 8):
        markers.append(title)
        if note:
            markers.append(note)
    result: list[str] = []
    seen: set[str] = set()
    for marker in markers:
        normalized = _normalize_for_match(marker)
        if len(normalized) < 6 or normalized in seen:
            continue
        seen.add(normalized)
        result.append(marker)
    return result


def _has_photo_specific_marker(text: Any, output: dict[str, Any]) -> bool:
    normalized_text = _normalize_for_match(text)
    if not normalized_text:
        return False
    for marker in _photo_specific_markers(output):
        normalized = _normalize_for_match(marker)
        if len(normalized) >= 6 and normalized in normalized_text:
            return True
        words = [word for word in normalized.split() if len(word) >= 5]
        if len(words) >= 2 and sum(1 for word in words if word in normalized_text) >= 2:
            return True
    return False


def _ensure_photo_specific_block(
    output: dict[str, Any],
    key: str,
    *,
    variant: str = "aging",
    max_chars: int,
) -> None:
    block = dict(output.get(key) if isinstance(output.get(key), dict) else {})
    text = str(block.get("text") or "")
    if text and _has_photo_specific_marker(text, output):
        block["text"] = _clip_text(text, max_chars)
        output[key] = block
        return
    note = _photo_context_sentence(output, variant)
    if note:
        block["text"] = _append_context_preserving_format(text, note, max_chars)
        output[key] = block


def _force_photo_specific_block(output: dict[str, Any], key: str, *, variant: str, max_chars: int) -> None:
    block = dict(output.get(key) if isinstance(output.get(key), dict) else {})
    text = str(block.get("text") or "")
    if text and _has_photo_specific_marker(text, output):
        block["text"] = _clip_text(text, max_chars)
        output[key] = block
        return
    note = _photo_context_sentence(output, variant)
    if not note:
        return
    note = _sanitize_photo_context_text(note, 128)
    if not note:
        return
    base = _strip_added_photo_context(text) or text
    available = max_chars - len(note) - 3
    if available > 48:
        base = _clip_text(base, available).rstrip(".")
        block["text"] = f"{base}. {note}." if base else f"{note}."
    else:
        block["text"] = _clip_text(note, max_chars)
    output[key] = block


def _ensure_face_strengths_core_promises(output: dict[str, Any]) -> None:
    strengths = dict(output.get("face_strengths") if isinstance(output.get("face_strengths"), dict) else {})
    text = str(strengths.get("text") or "")
    bullets = [str(item) for item in strengths.get("bullets", []) if str(item or "").strip()] if isinstance(strengths.get("bullets"), list) else []
    combined = _normalize_for_match(" ".join([text, *bullets]))
    required_additions = {
        "форма лица / овал": "Форма и овал выглядят гармонично.",
        "скулы / костная база": "Скулы и костная база дают природную опору.",
        "глаза / взгляд": "Глаза и взгляд создают выразительность.",
        "симметрия / пропорции": "Симметрия и пропорции дают лицу гармоничный баланс.",
        "природный актив / эффект процедур": "Это природный актив: такие черты часто стараются подчеркнуть процедурами, а у тебя они уже есть.",
    }
    for label, markers in FACE_STRENGTH_MARKERS.items():
        if any(marker in combined for marker in markers):
            continue
        addition = required_additions[label]
        if label == "природный актив / эффект процедур" and len(text) + len(addition) + 1 <= TEXT_LIMITS["face_strengths.text"]:
            text = f"{text.rstrip('.')}. {addition}" if text else addition
        elif addition not in bullets:
            bullets.append(addition)
        combined = _normalize_for_match(" ".join([text, *bullets]))
    strengths["text"] = _clip_text(text, TEXT_LIMITS["face_strengths.text"])
    strengths["bullets"] = bullets[: LIST_LIMITS["face_strengths.bullets"]]
    output["face_strengths"] = strengths


def _compact_ai_text(value: Any, max_chars: int, *, strip_labels: tuple[str, ...] = ()) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if strip_labels:
        text = _strip_known_block_label(text, strip_labels)
    text = _strip_added_photo_context(text)
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    return _clip_text(text, max_chars).rstrip(".")


def _strip_added_photo_context(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n{2,}", value) if part.strip()]
    kept: list[str] = []
    prefixes = (
        "визуально",
        "тип кожи",
        "форма скулы и взгляд",
        "природная база лица уже есть",
        "сильная природная база уже видна",
        "по фото ведущие маркеры",
        "по фото выделяются",
        "по фото особенно читается",
        "на твоем фото эта динамика",
        "на твоем фото это связано",
        "сейчас первыми зонами внимания",
        "сейчас первые зоны внимания",
        "фокус текущего фото",
        "фокус по фото",
        "главный маршрут по фото",
        "первый маршрут по фото",
        "главный маршрут фейс фитнеса",
        "главный маршрут фейс-фитнеса",
        "по логике типа работа идет",
        "первый маршрут текущего фото",
        "главный маршрут сейчас",
    )
    for part in parts:
        normalized = _normalize_for_match(part)
        if any(normalized.startswith(prefix) for prefix in prefixes):
            continue
        kept.append(part)
    return " ".join(kept).strip()


def _cap_first(value: str) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def _photo_focus_note(output: dict[str, Any], max_chars: int = 96) -> str:
    items = _photo_zone_context_items(output, 2)
    if items:
        return _clip_text(_format_photo_context_parts(items), max_chars).rstrip(".")
    evidence = _photo_evidence_context_items(output, 2)
    if evidence:
        return _clip_text("; ".join(item[:1].lower() + item[1:] for item in evidence), max_chars).rstrip(".")
    return ""


def _type_base_adjective(type_id: str) -> str:
    return {
        "muscular": "сильной",
        "deformation_edema": "мягкой женственной",
        "fine_wrinkle": "изящной",
        "tired_mixed": "мягкой гармоничной",
    }.get(type_id, "сильной")


def _type_focus_public(type_id: str, mixed_components: list[str] | None = None) -> str:
    if type_id == "tired_mixed" and mixed_components:
        components = _unique_mixed_components(mixed_components)
        if len(components) > 1:
            focus_parts = [MIXED_COMPONENT_FOCUS[item] for item in components[:2] if item in MIXED_COMPONENT_FOCUS]
            return " + ".join(focus_parts)
    return {
        "muscular": "расслабление гипертонуса, мягкость мимики и баланс мышц",
        "deformation_edema": "лимфодренаж, работа с шеей и осанкой, отток жидкости и поддержка овала",
        "fine_wrinkle": "увлажнение, питание тканей, микроциркуляция и мягкая работа с мышцами",
        "tired_mixed": "свежесть, мягкий тонус, микроциркуляция, лимфодренаж и расслабление",
    }.get(type_id, AGING_KNOWLEDGE_BASE["tired_mixed"]["main_focus"])


def _fit_parts(parts: list[str], max_chars: int) -> str:
    selected: list[str] = []
    for part in parts:
        clean = re.sub(r"\s+", " ", str(part or "")).strip(" .")
        if not clean:
            continue
        candidate = ". ".join([*selected, clean]).strip()
        if len(candidate) > max_chars:
            break
        selected.append(clean)
    if not selected and parts:
        return _clip_text(parts[0], max_chars)
    return (". ".join(selected).strip(" .") + ".") if selected else ""


def _format_skin_visual_age_block(output: dict[str, Any]) -> None:
    block = dict(output.get("skin_visual_age") if isinstance(output.get("skin_visual_age"), dict) else {})
    visual_age = block.get("visual_age")
    label = str(block.get("age_delta_label") or "")
    body = _compact_ai_text(
        block.get("text"),
        74,
        strip_labels=("Биологический возраст кожи", "Визуальный возраст кожи"),
    )
    body = re.sub(r"^кожа\s+выглядит\s+ухоженной[;,.]?\s*", "", body, flags=re.IGNORECASE)
    body = re.sub(r"^(и\s+)?живой[.!]?$", "", body, flags=re.IGNORECASE).strip()
    if _normalize_for_match(body).startswith("визуально"):
        body = ""
    body = _cap_first(body) or "Кожа выглядит ухоженной и живой"
    focus = _photo_context_focus(output, "свежесть взгляда")
    age_line = f"Визуально — на {visual_age} лет ({label})" if visual_age else ""
    text = (
        f"{body}. {age_line}. По фото фокус — {focus}; эти зоны хорошо отвечают на регулярность."
    )
    block["text"] = _clip_text(text, TEXT_LIMITS["skin_visual_age.text"])
    output["skin_visual_age"] = block


def _format_skin_type_block(output: dict[str, Any]) -> None:
    block = dict(output.get("skin_type") if isinstance(output.get("skin_type"), dict) else {})
    type_name = normalize_skin_type_name(block.get("type_name"))
    focus = _photo_context_focus(output, "центральная зона")
    short_name = type_name[:1].lower() + type_name[1:]
    body = _compact_ai_text(block.get("text"), 116, strip_labels=("Тип кожи",))
    body = re.sub(r"^у\s+вас\s+", "", body, flags=re.IGNORECASE).strip()
    while re.match(rf"^{re.escape(short_name)}\b", body, flags=re.IGNORECASE):
        body = re.sub(rf"^{re.escape(short_name)}[.:\s—-]*", "", body, flags=re.IGNORECASE).strip()
    normalized_body = _normalize_for_match(body)
    if not body or normalized_body.startswith("комбинированная кожа") or normalized_body.startswith("сухая кожа") or normalized_body.startswith("чувствительная кожа"):
        if "сух" in _normalize_for_match(type_name):
            body = "Плюс — деликатная текстура и мягкий ровный тон"
        elif "чувств" in _normalize_for_match(type_name):
            body = "Плюс — кожа быстро отвечает на бережный уход"
        else:
            body = "Плюс — кожа хорошо держит каркас лица"
    text = _fit_parts(
        [
            f"Тип кожи: {short_name}",
            body,
            f"Фокус текущего фото — {focus}; при уходе тон может выглядеть свежее и ровнее",
        ],
        TEXT_LIMITS["skin_type.text"],
    )
    block["type_name"] = type_name
    block["text"] = text
    block["bullets"] = build_skin_type_bullets(type_name)[: LIST_LIMITS["skin_type.bullets"]]
    output["skin_type"] = block


def _format_face_strengths_block(output: dict[str, Any]) -> None:
    block = dict(output.get("face_strengths") if isinstance(output.get("face_strengths"), dict) else {})
    type_id = str((output.get("aging_type") or {}).get("type_id") or "tired_mixed")
    body = _compact_ai_text(
        block.get("text"),
        210,
        strip_labels=("Ваши сильные стороны лица", "Ваши сильные стороны", "Форма, скулы и взгляд"),
    )
    if not body:
        body = _compact_ai_text(build_face_strengths_text(type_id), 210)
    focus = _photo_focus_note(output, 78) or _photo_context_focus(output, "скулы и взгляд")
    asset_sentence = "Форма, скулы, взгляд, симметрия и пропорции выглядят природным активом — такие черты часто подчеркивают процедурами"
    parts = [asset_sentence, f"По фото особенно читается: {focus}", body]
    text = _fit_parts(
        parts,
        TEXT_LIMITS["face_strengths.text"],
    )
    block["text"] = text
    existing_bullets = [str(item) for item in block.get("bullets", []) if str(item or "").strip()] if isinstance(block.get("bullets"), list) else []
    block["bullets"] = (
        existing_bullets
        or [
            "Форма и овал выглядят гармонично.",
            "Скулы и костная база дают природную опору.",
            "Глаза и пропорции создают выразительность.",
        ]
    )[: LIST_LIMITS["face_strengths.bullets"]]
    output["face_strengths"] = block


def _format_face_fitness_block(output: dict[str, Any], type_id: str) -> None:
    block = dict(output.get("face_fitness_benefits") if isinstance(output.get("face_fitness_benefits"), dict) else {})
    mixed_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    body = _compact_ai_text(block.get("text"), 188, strip_labels=("Что даст фейс-фитнес",))
    body = _strip_added_photo_context(body)
    if not body:
        body = build_face_fitness_benefits_text(type_id)
    focus = _photo_context_focus(output, "ключевые зоны лица")
    type_focus = _type_focus_public(type_id, mixed_components)
    if "природ" not in _normalize_for_match(body):
        body = f"Сильная природная база уже видна. {body}".strip()
    text = _fit_parts(
        [
            body,
            f"По логике типа работа идет через {type_focus}",
            f"Первый маршрут текущего фото — {focus}",
        ],
        TEXT_LIMITS["face_fitness_benefits.text"],
    )
    block["text"] = text
    if not isinstance(block.get("bullets"), list) or not block["bullets"]:
        block["bullets"] = build_face_fitness_benefits_bullets(type_id)
    block["bullets"] = [str(item) for item in block["bullets"] if str(item or "").strip()][: LIST_LIMITS["face_fitness_benefits.bullets"]]
    output["face_fitness_benefits"] = block


def _format_growth_zones_block(output: dict[str, Any], type_id: str) -> None:
    block = dict(output.get("growth_zones") if isinstance(output.get("growth_zones"), dict) else {})
    mixed_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    focus = _photo_context_focus(output, "ключевые зоны")
    type_focus = _type_focus_public(type_id, mixed_components)
    block["summary"] = _clip_text(f"Главный фокус: {type_focus}. По фото — {focus}.", TEXT_LIMITS["growth_zones.summary"])
    items = block.get("items") if isinstance(block.get("items"), list) else []
    zone_titles = _photo_context_titles(output, 4)
    block["items"] = [str(item) for item in (items or zone_titles) if str(item or "").strip()][:4]
    output["growth_zones"] = block


def _format_final_summary_block(output: dict[str, Any], type_id: str) -> None:
    block = dict(output.get("final_summary") if isinstance(output.get("final_summary"), dict) else {})
    mixed_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    body = _compact_ai_text(block.get("text"), 150, strip_labels=("Итог", "Финал", "Финальная фраза"))
    body = re.sub(r"\bИменно\s+для\s+этого\s+создан[а-я\s]*курс\.?\s*$", "", body, flags=re.IGNORECASE).strip()
    focus = _photo_context_focus(output, "главные зоны лица")
    type_focus = _type_focus_public(type_id, mixed_components)
    opening = body or f"У тебя красивое лицо с {_type_base_adjective(type_id)} природной базой"
    parts = [opening]
    normalized_body = _normalize_for_match(opening)
    if "главн" not in normalized_body or _normalize_for_match(focus) not in normalized_body:
        parts.append(f"Главный маршрут сейчас — {type_focus}; на фото особенно важны {focus}")
    if "курс" not in normalized_body:
        parts.append("Именно для этого создан этот курс")
    text = _fit_parts(parts, TEXT_LIMITS["final_summary.text"])
    block["text"] = text
    block["quote"] = _clip_text(block.get("quote") or "«Именно для этого создан этот курс.»", TEXT_LIMITS["final_summary.quote"])
    output["final_summary"] = block


def _soften_forecast_text(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip(" .")
    for _ in range(4):
        deduped = re.sub(r"^([^:]{3,44}):\s*\1:\s*", r"\1: ", value, flags=re.IGNORECASE)
        if deduped == value:
            break
        value = deduped
    value = re.sub(r"^ты\s+заметишь,\s+как\s+", "", value, flags=re.IGNORECASE)
    replacements = (
        (r"\bбудет выглядеть\b", "может выглядеть"),
        (r"\bстанет\b", "может стать"),
        (r"\bстанут\b", "могут стать"),
        (r"\bстало\b", "может выглядеть"),
        (r"\bулучшится\b", "может улучшиться"),
        (r"\bуменьшится\b", "может уменьшиться"),
        (r"\bуменьшилась\b", "может уменьшиться"),
        (r"\bприобретут\b", "могут приобрести"),
        (r"\bзначительно\b", "заметно"),
        (r"\bточно\b", "обычно"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(r"\s+(и|а|но|в|с|к|по|для|на|о)\.?$", "", value, flags=re.IGNORECASE)
    return _clip_text(value, TEXT_LIMITS["time_forecast.items.text"])


def enforce_protocol_v4_writing_format(output: dict[str, Any]) -> dict[str, Any]:
    """Keep the model's photo analysis, but make the card copy follow the approved format."""
    result = dict(output)
    aging = dict(result.get("aging_type") if isinstance(result.get("aging_type"), dict) else {})
    client = result.get("client") if isinstance(result.get("client"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    if type_id not in AGING_TYPE_NAMES:
        return result
    mixed_components = mixed_combo_type_ids_from_payload(result) if type_id == "tired_mixed" else []
    type_name = AGING_TYPE_NAMES[type_id]

    aging_text = _strip_short_type_intro(aging.get("text"), type_name)
    aging_text = _strip_known_block_label(aging_text, ("Характеристика этого типа", "Что происходит внутри"))
    aging_text = _strip_added_photo_context(aging_text)
    normalized_aging_text = _normalize_for_match(aging_text)
    aging_marker_count = (
        _combo_marker_count(normalized_aging_text, mixed_components, TYPE_MARKERS)
        if type_id == "tired_mixed" and len(mixed_components) > 1
        else _marker_count(normalized_aging_text, TYPE_MARKERS[type_id])
    )
    if len(normalized_aging_text) < 80 or aging_marker_count < 2:
        aging_text = build_aging_type_text(type_id, mixed_components)
    aging_text = _with_block_label("Характеристика этого типа", aging_text, TEXT_LIMITS["aging_type.text"])
    aging_text = _append_context_preserving_format(aging_text, _photo_context_sentence(result, "aging"), TEXT_LIMITS["aging_type.text"])
    aging["text"] = aging_text
    result["aging_type"] = aging

    future = dict(result.get("future_changes") if isinstance(result.get("future_changes"), dict) else {})
    future_text = _strip_known_block_label(str(future.get("text") or ""), ("Как меняется лицо со временем",))
    future_text = _strip_added_photo_context(future_text)
    if not is_future_changes_text_valid(future_text, type_id, mixed_components):
        future_text = build_future_changes_text(type_id, mixed_components)
    future_text = _with_block_label("Как меняется лицо со временем", future_text, TEXT_LIMITS["future_changes.text"])
    future_text = _append_context_preserving_format(future_text, _photo_context_sentence(result, "future"), TEXT_LIMITS["future_changes.text"])
    future["text"] = future_text
    result["future_changes"] = future

    age_changes = dict(result.get("age_changes") if isinstance(result.get("age_changes"), dict) else {})
    age_text = str(age_changes.get("text") or "")
    if validate_age_changes_timeline({**result, "age_changes": {**age_changes, "text": age_text}}):
        age_text = build_age_changes_text(type_id, client.get("age") if isinstance(client.get("age"), int) else None, mixed_components)
    age_text = _strip_added_photo_context(age_text)
    age_changes["text"] = _format_age_changes_with_photo_context(
        age_text,
        _photo_context_sentence(result, "age"),
        result,
        TEXT_LIMITS["age_changes.text"],
    )
    result["age_changes"] = age_changes

    _format_skin_visual_age_block(result)
    _format_skin_type_block(result)
    _format_face_strengths_block(result)
    _ensure_face_strengths_core_promises(result)
    for photo_key, photo_variant in (
        ("skin_visual_age", "age"),
        ("skin_type", "aging"),
        ("face_strengths", "aging"),
        ("face_fitness_benefits", "aging"),
        ("final_summary", "aging"),
    ):
        _force_photo_specific_block(result, photo_key, variant=photo_variant, max_chars=TEXT_LIMITS[f"{photo_key}.text"])
    _format_face_fitness_block(result, type_id)
    _format_growth_zones_block(result, type_id)
    _format_final_summary_block(result, type_id)
    _force_photo_specific_block(result, "face_fitness_benefits", variant="aging", max_chars=TEXT_LIMITS["face_fitness_benefits.text"])
    _force_photo_specific_block(result, "final_summary", variant="aging", max_chars=TEXT_LIMITS["final_summary.text"])

    forecast = dict(result.get("time_forecast") if isinstance(result.get("time_forecast"), dict) else {})
    forecast["intro"] = "Если ты начнёшь заниматься по нашей системе:"
    raw_items = forecast.get("items") if isinstance(forecast.get("items"), list) else []
    items: list[dict[str, str]] = []
    personalized_items = build_personalized_forecast_items(type_id, result)
    forecast_titles = _photo_context_titles(result, 3)
    for index, period in enumerate(FORECAST_PERIODS):
        raw_item = raw_items[index] if index < len(raw_items) and isinstance(raw_items[index], dict) else {}
        text = raw_item.get("text") or personalized_items[index]["text"]
        softened = _soften_forecast_text(text)
        if forecast_titles and not _has_photo_specific_marker(softened, result):
            zone = forecast_titles[min(index, len(forecast_titles) - 1)]
            normalized_zone = _normalize_for_match(zone)
            if not _normalize_for_match(softened).startswith(normalized_zone):
                softened = _soften_forecast_text(f"{zone}: {softened}")
        items.append({"period": period, "text": softened})
    forecast["items"] = items
    result["time_forecast"] = forecast
    return result


def _photo_context_titles(payload: dict[str, Any] | None, limit: int = 2) -> list[str]:
    return [title[:1].lower() + title[1:] for title, _ in _photo_zone_context_items(payload, limit)]


def _photo_context_focus(payload: dict[str, Any] | None, fallback: str = "зона глаз") -> str:
    titles = _photo_context_titles(payload, 2)
    if not titles:
        evidence = _photo_evidence_context_items(payload, 2)
        titles = [item[:1].lower() + item[1:] for item in evidence]
    if not titles:
        return fallback
    if len(titles) == 1:
        return titles[0]
    return f"{titles[0]} и {titles[1]}"


def _photo_positive_focus(payload: dict[str, Any] | None) -> str:
    source = payload if isinstance(payload, dict) else {}
    zones = _iter_photo_zone_blocks(source)
    positive: list[tuple[str, str]] = []
    for zone in zones:
        status = _normalize_for_match(zone.get("status") or zone.get("color"))
        if status not in {"green", "good"}:
            continue
        title = _sanitize_photo_context_text(zone.get("title") or zone.get("name") or zone.get("label"), 46)
        note = ""
        for field in PHOTO_CONTEXT_ZONE_FIELDS:
            note = _sanitize_photo_context_text(zone.get(field), 96)
            if note:
                break
        if title:
            positive.append((title, note))
    if positive:
        title, note = positive[0]
        title = title[:1].lower() + title[1:]
        if note:
            return f"{title} — {note[:1].lower() + note[1:]}"
        return title
    focus = _photo_context_focus(source, "скулы и взгляд")
    return focus


def _block_text_from(output: dict[str, Any], key: str, fallback: str = "") -> str:
    block = output.get(key) if isinstance(output.get(key), dict) else {}
    value = block.get("text") or block.get("description") or block.get("summary")
    if not value:
        value = _section_text(output, key) or fallback
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _set_block_text(output: dict[str, Any], key: str, text: str) -> None:
    block = dict(output.get(key) if isinstance(output.get(key), dict) else {})
    block["text"] = text
    output[key] = block


def build_personalized_skin_visual_age_text(base_text: Any, payload: dict[str, Any] | None = None) -> str:
    focus = _photo_context_focus(payload, "свежесть взгляда")
    text = f"Кожа выглядит ухоженной; визуальный возраст больше задают {focus}. Хорошая новость — эти зоны хорошо отвечают на мягкую регулярность."
    if len(text) <= TEXT_LIMITS["skin_visual_age.text"]:
        return text
    return _clip_text(f"Кожа выглядит ухоженной; визуальный возраст больше задают {focus}.", TEXT_LIMITS["skin_visual_age.text"])


def build_personalized_skin_type_text(
    type_name: Any,
    base_text: Any = "",
    payload: dict[str, Any] | None = None,
) -> str:
    normalized = normalize_skin_type_name(type_name)
    focus = _photo_context_focus(payload, "зона глаз")
    short_name = normalized[:1].lower() + normalized[1:]
    text = (
        f"У вас {short_name}. Плюс этого типа — кожа хорошо держит каркас лица. "
        f"По фото больше внимания просит {focus}; при регулярном уходе тон выглядит свежее и ровнее."
    )
    if len(text) <= TEXT_LIMITS["skin_type.text"]:
        return text
    return _clip_text(
        f"У вас {short_name}. Плюс этого типа — кожа держит каркас. {focus.capitalize()} просит увлажнения; при уходе тон свежее.",
        TEXT_LIMITS["skin_type.text"],
    )


def build_personalized_face_strengths_text(
    type_id: str,
    base_text: Any = "",
    payload: dict[str, Any] | None = None,
) -> str:
    positive_focus = _photo_positive_focus(payload)
    focus = _photo_context_focus(payload, "зона глаз")
    text = (
        f"У вас гармоничная форма лица: на фото особенно красиво читается {positive_focus}. "
        f"Скулы и костная база дают лицу опору, глаза остаются выразительной сильной зоной. "
        f"Пропорции выглядят природным активом — то, что многие подчеркивают процедурами, у вас уже есть."
    )
    if len(text) <= TEXT_LIMITS["face_strengths.text"]:
        return text
    return _clip_text(
        f"У вас гармоничная форма лица, скулы дают опору, а глаза — сильная зона. На фото это особенно видно через {focus}. Пропорции выглядят природным активом, который многие подчеркивают процедурами.",
        TEXT_LIMITS["face_strengths.text"],
    )


def build_personalized_face_fitness_benefits_text(
    type_id: str,
    base_text: Any = "",
    payload: dict[str, Any] | None = None,
) -> str:
    focus = _photo_context_focus(payload, "зона глаз")
    type_focus = AGING_KNOWLEDGE_BASE.get(type_id, AGING_KNOWLEDGE_BASE["tired_mixed"])["main_focus"]
    text = (
        f"Фейс-фитнес здесь не меняет черты, а раскрывает вашу природную базу. "
        f"В вашем маршруте первый фокус — {focus}. Главная логика типа: {type_focus}; за счет этого лицо может выглядеть свежее, мягче и собраннее."
    )
    return _clip_text(text, TEXT_LIMITS["face_fitness_benefits.text"])


def build_personalized_forecast_items(
    type_id: str,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    titles = _photo_context_titles(payload, 3)
    first = titles[0] if len(titles) > 0 else "взгляд"
    second = titles[1] if len(titles) > 1 else first
    third = titles[2] if len(titles) > 2 else "овал"
    if type_id == "muscular":
        third = "мимика и овал"
    elif type_id == "deformation_edema":
        third = "овал и нижняя треть"
    elif type_id == "fine_wrinkle":
        third = "текстура кожи"
    return [
        {"period": "Через 2 недели", "text": _clip_text(f"{first} может выглядеть мягче и свежее.", TEXT_LIMITS["time_forecast.items.text"])},
        {"period": "Через 3–4 недели", "text": _clip_text(f"работа с зоной «{second}» станет заметнее в выражении лица.", TEXT_LIMITS["time_forecast.items.text"])},
        {"period": "Через 6–8 недель", "text": _clip_text(f"работа с зоной «{third}» поможет закрепить эффект регулярности.", TEXT_LIMITS["time_forecast.items.text"])},
    ]


def build_personalized_final_summary_text(
    type_id: str,
    base_text: Any = "",
    payload: dict[str, Any] | None = None,
) -> str:
    focus = _photo_context_focus(payload, "главные зоны лица")
    type_focus = AGING_KNOWLEDGE_BASE.get(type_id, AGING_KNOWLEDGE_BASE["tired_mixed"])["main_focus"]
    text = (
        f"У вас красивое лицо с сильной природной базой. Главное сейчас — мягко поддержать ключевые зоны ({focus}) "
        f"и идти по логике типа: {type_focus}. Так раскрывается ваша настоящая красота. Именно для этого создан этот курс."
    )
    return _clip_text(text, TEXT_LIMITS["final_summary.text"])


def normalize_protocol_v4_shape(output: dict[str, Any]) -> dict[str, Any]:
    """Repair common AI shape slips without replacing the AI's photo-specific content."""
    result = dict(output if isinstance(output, dict) else {})
    result["protocol_version"] = PROTOCOL_VERSION

    client = dict(result.get("client") if isinstance(result.get("client"), dict) else {})
    skin_age = dict(result.get("skin_visual_age") if isinstance(result.get("skin_visual_age"), dict) else {})
    passport_age = client.get("age") or skin_age.get("passport_age") or skin_age.get("age") or 30
    try:
        passport_age = int(passport_age)
    except Exception:
        passport_age = 30
    client["age"] = max(1, min(110, passport_age))
    client.setdefault("name", "")
    client.setdefault("date", "")
    result["client"] = client

    visual_age = skin_age.get("visual_age")
    try:
        visual_age = int(visual_age)
    except Exception:
        visual_age = 0
    skin_age["section_number"] = "01"
    skin_age["title"] = "Биологический возраст кожи"
    skin_age["passport_age"] = client["age"]
    skin_age["visual_age"] = target_visual_age(client["age"], visual_age)
    skin_age["age_delta"] = skin_age["visual_age"] - client["age"]
    skin_age["age_delta_label"] = age_delta_label(skin_age["age_delta"])
    skin_age["text"] = sync_visual_age_text(skin_age.get("text") or skin_age.get("description") or "", skin_age["visual_age"])
    result["skin_visual_age"] = skin_age

    block_defaults = {
        "skin_type": ("02", "Тип кожи"),
        "face_strengths": ("03", "Ваши сильные стороны лица"),
        "future_changes": ("05", "Какие изменения будут со временем"),
        "face_fitness_benefits": ("07", "Что даст фейс-фитнес"),
    }
    for key, (section, title) in block_defaults.items():
        block = dict(result.get(key) if isinstance(result.get(key), dict) else {})
        block["section_number"] = section
        block["title"] = str(block.get("title") or title)
        block["text"] = str(block.get("text") or block.get("description") or block.get("summary") or "")
        bullets = block.get("bullets")
        if not isinstance(bullets, list):
            bullets = []
        block["bullets"] = [str(item) for item in bullets if str(item or "").strip()]
        result[key] = block
    skin_type = dict(result["skin_type"])
    skin_type["type_name"] = normalize_skin_type_name(skin_type.get("type_name") or skin_type.get("type") or "")
    result["skin_type"] = skin_type

    aging = dict(result.get("aging_type") if isinstance(result.get("aging_type"), dict) else {})
    type_id = str(aging.get("type_id") or "")
    if type_id not in AGING_TYPE_NAMES:
        type_id = _type_from_partial(result)
    aging["section_number"] = "04"
    aging["title"] = "Тип старения"
    aging["type_id"] = type_id
    aging["type_name"] = AGING_TYPE_NAMES[type_id]
    mixed_components = mixed_combo_type_ids_from_payload({"aging_type": aging}) if type_id == "tired_mixed" else []
    aging["display_name"] = build_aging_type_display_name(type_id, mixed_components)
    aging["confidence"] = aging.get("confidence") if aging.get("confidence") in {"low", "medium", "high"} else "medium"
    aging["evidence"] = [str(item) for item in aging.get("evidence", []) if str(item or "").strip()] if isinstance(aging.get("evidence"), list) else []
    aging["text"] = str(aging.get("text") or aging.get("description") or "")
    result["aging_type"] = aging

    age_changes = dict(result.get("age_changes") if isinstance(result.get("age_changes"), dict) else {})
    age_changes["section_number"] = "06"
    age_changes["title"] = "Первые изменения по возрасту"
    age_changes["text"] = str(age_changes.get("text") or age_changes.get("description") or "")
    result["age_changes"] = age_changes

    forecast = dict(result.get("time_forecast") if isinstance(result.get("time_forecast"), dict) else {})
    raw_items = forecast.get("items") if isinstance(forecast.get("items"), list) else []
    normalized_items: list[dict[str, str]] = []
    for index, period in enumerate(FORECAST_PERIODS):
        item = raw_items[index] if index < len(raw_items) else {}
        if isinstance(item, dict):
            text = item.get("text") or item.get("description") or item.get("value") or ""
        else:
            text = str(item or "")
            for known_period in FORECAST_PERIODS:
                text = text.replace(known_period, "").strip(" —-:•")
        normalized_items.append({"period": period, "text": _clip_text(text, TEXT_LIMITS["time_forecast.items.text"])})
    forecast["section_number"] = "08"
    forecast["title"] = "Прогноз по времени"
    forecast["intro"] = forecast.get("intro") or "Если ты начнёшь заниматься по нашей системе:"
    forecast["items"] = normalized_items
    result["time_forecast"] = forecast

    growth = dict(result.get("growth_zones") if isinstance(result.get("growth_zones"), dict) else {})
    raw_growth_items = growth.get("items") if isinstance(growth.get("items"), list) else []
    growth_items: list[str] = []
    for item in raw_growth_items:
        if isinstance(item, dict):
            value = item.get("zone") or item.get("title") or item.get("name") or item.get("text") or item.get("priority")
        else:
            value = item
        value = _sanitize_photo_context_text(value, 50)
        if value:
            growth_items.append(value)
    growth["section_number"] = "09"
    growth["title"] = "Зоны роста"
    growth["summary"] = str(growth.get("summary") or growth.get("text") or "")
    growth["items"] = growth_items
    result["growth_zones"] = growth

    status_aliases = {"good": "green", "attention": "yellow", "focus": "orange", "priority": "red"}
    zone_map = dict(result.get("zone_map") if isinstance(result.get("zone_map"), dict) else {})
    raw_zones = zone_map.get("zones") if isinstance(zone_map.get("zones"), list) else []
    zones: list[dict[str, Any]] = []
    for index, zone in enumerate([item for item in raw_zones if isinstance(item, dict)][:6], start=1):
        raw_status = _normalize_for_match(zone.get("status") or zone.get("color"))
        status = raw_status if raw_status in {"green", "yellow", "orange", "red"} else status_aliases.get(raw_status, "yellow")
        title = _sanitize_photo_context_text(zone.get("title") or zone.get("name") or zone.get("label"), 44) or f"Зона {index}"
        zones.append(
            {
                "id": str(zone.get("id") or f"zone_{index}"),
                "number": int(zone.get("number") or index),
                "title": title,
                "status": status,
                "meaning": _sanitize_photo_context_text(
                    zone.get("meaning") or zone.get("short_comment") or zone.get("reason") or zone.get("description") or zone.get("what_is_visible"),
                    120,
                )
                or f"{title} помогает понять главный маршрут работы.",
                "anchor": zone.get("anchor") if isinstance(zone.get("anchor"), dict) else {"x": 50, "y": 30 + index * 7},
                "shape": zone.get("shape") if isinstance(zone.get("shape"), dict) else {},
            }
        )
    if not zones:
        zones = []
    result["zone_map"] = {"title": zone_map.get("title") or "Карта зон лица", "zones": zones}

    final = dict(result.get("final_summary") if isinstance(result.get("final_summary"), dict) else {})
    final["text"] = str(final.get("text") or final.get("main_conclusion") or "")
    final["quote"] = str(final.get("quote") or "")
    result["final_summary"] = final
    result["images"] = result.get("images") if isinstance(result.get("images"), dict) else {"face_image_url": "", "face_object_position": "50% 42%"}
    result["footer"] = result.get("footer") if isinstance(result.get("footer"), dict) else {"disclaimer": FooterV4().disclaimer}
    result["meta"] = result.get("meta") if isinstance(result.get("meta"), dict) else {"main_segment": type_id, "lead_temperature": "warm", "fallback_used": False}
    return result


def personalize_photo_specific_blocks(output: dict[str, Any]) -> dict[str, Any]:
    """Make every visible block depend on the current face analysis while staying inside the KB."""
    result = dict(output)
    aging = result.get("aging_type") if isinstance(result.get("aging_type"), dict) else {}
    type_id = str(aging.get("type_id") or "tired_mixed")
    if type_id not in AGING_TYPE_NAMES:
        type_id = "tired_mixed"

    skin_age = dict(result.get("skin_visual_age") if isinstance(result.get("skin_visual_age"), dict) else {})
    skin_age["text"] = build_personalized_skin_visual_age_text(skin_age.get("text"), result)
    result["skin_visual_age"] = skin_age

    skin_type = dict(result.get("skin_type") if isinstance(result.get("skin_type"), dict) else {})
    skin_type["text"] = build_personalized_skin_type_text(skin_type.get("type_name"), skin_type.get("text"), result)
    skin_type["bullets"] = build_skin_type_bullets(skin_type.get("type_name"))[: LIST_LIMITS["skin_type.bullets"]]
    result["skin_type"] = skin_type

    strengths = dict(result.get("face_strengths") if isinstance(result.get("face_strengths"), dict) else {})
    strengths["text"] = build_personalized_face_strengths_text(type_id, strengths.get("text"), result)
    if not isinstance(strengths.get("bullets"), list) or not strengths["bullets"]:
        strengths["bullets"] = build_face_strengths_bullets(type_id)
    result["face_strengths"] = strengths

    benefits = dict(result.get("face_fitness_benefits") if isinstance(result.get("face_fitness_benefits"), dict) else {})
    benefits["text"] = build_personalized_face_fitness_benefits_text(type_id, benefits.get("text"), result)
    if not isinstance(benefits.get("bullets"), list) or not benefits["bullets"]:
        benefits["bullets"] = build_face_fitness_benefits_bullets(type_id)
    result["face_fitness_benefits"] = benefits

    forecast = dict(result.get("time_forecast") if isinstance(result.get("time_forecast"), dict) else {})
    forecast["items"] = build_personalized_forecast_items(type_id, result)
    result["time_forecast"] = forecast

    final = dict(result.get("final_summary") if isinstance(result.get("final_summary"), dict) else {})
    final["text"] = build_personalized_final_summary_text(type_id, final.get("text"), result)
    final["quote"] = final.get("quote") or "«Именно для этого создан этот курс.»"
    result["final_summary"] = final
    return result


def build_personalized_aging_type_text(
    type_id: str,
    mixed_components: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    base = build_aging_type_text(type_id, mixed_components)
    return _append_photo_context(base, _photo_context_sentence(payload, "aging"), TEXT_LIMITS["aging_type.text"])


def build_personalized_future_changes_text(
    type_id: str,
    mixed_components: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    base = build_future_changes_text(type_id, mixed_components)
    return _append_photo_context(base, _photo_context_sentence(payload, "future"), TEXT_LIMITS["future_changes.text"])


def build_personalized_age_changes_text(
    type_id: str,
    passport_age: int | None,
    mixed_components: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    base = build_age_changes_text(type_id, passport_age, mixed_components)
    return _append_photo_context(base, _photo_context_sentence(payload, "age"), TEXT_LIMITS["age_changes.text"])


def _preserve_ai_block_text(value: Any, fallback: str, max_chars: int) -> str:
    """Keep only the model's analysis text; missing copy must fail validation/retry."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text:
        return _clip_text(text, max_chars)
    return ""


def canonicalize_knowledge_base_blocks(output: dict[str, Any]) -> dict[str, Any]:
    """Lock block metadata to the selected type without replacing AI-written analysis."""
    result = dict(output)
    aging = result.get("aging_type") if isinstance(result.get("aging_type"), dict) else {}
    client = result.get("client") if isinstance(result.get("client"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    if type_id not in AGING_TYPE_NAMES:
        return result
    mixed_components = mixed_combo_type_ids_from_payload(result) if type_id == "tired_mixed" else []

    aging_block = dict(aging)
    aging_block["section_number"] = "04"
    aging_block["title"] = "Тип старения"
    aging_block["type_name"] = AGING_TYPE_NAMES[type_id]
    if type_id == "tired_mixed" and len(mixed_components) > 1:
        aging_block["combo_type_ids"] = mixed_components
        aging_block["combo_type_names"] = _mixed_component_names(mixed_components)
    else:
        aging_block["combo_type_ids"] = []
        aging_block["combo_type_names"] = []
    aging_block["display_name"] = build_aging_type_display_name(type_id, mixed_components)
    aging_block["text"] = _preserve_ai_block_text(
        aging_block.get("text") or aging_block.get("description"),
        "",
        TEXT_LIMITS["aging_type.text"],
    )
    result["aging_type"] = aging_block

    future = dict(result.get("future_changes") if isinstance(result.get("future_changes"), dict) else {})
    future["section_number"] = "05"
    future["title"] = "Какие изменения будут со временем"
    future["text"] = _preserve_ai_block_text(
        future.get("text") or future.get("description") or future.get("summary"),
        "",
        TEXT_LIMITS["future_changes.text"],
    )
    bullets = future.get("bullets") if isinstance(future.get("bullets"), list) else []
    future["bullets"] = [_clip_text(item, 90) for item in bullets if str(item or "").strip()][: LIST_LIMITS["future_changes.bullets"]]
    result["future_changes"] = future

    age_changes = dict(result.get("age_changes") if isinstance(result.get("age_changes"), dict) else {})
    age_changes["section_number"] = "06"
    age_changes["title"] = "Первые изменения по возрасту"
    age_changes["text"] = _preserve_ai_block_text(
        age_changes.get("text") or age_changes.get("description"),
        "",
        TEXT_LIMITS["age_changes.text"],
    )
    result["age_changes"] = age_changes
    return result


def repair_protocol_v4_validation_edges(output: dict[str, Any]) -> dict[str, Any]:
    """Repair only metadata. Copy itself must remain AI-written and validation-owned."""
    result = dict(output)
    aging = result.get("aging_type") if isinstance(result.get("aging_type"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    if type_id not in AGING_TYPE_NAMES:
        return result

    skin_type = dict(result.get("skin_type") if isinstance(result.get("skin_type"), dict) else {})
    skin_type_name = normalize_skin_type_name(skin_type.get("type_name"))
    skin_type["type_name"] = skin_type_name
    result["skin_type"] = skin_type
    return result


def validate_age_changes_timeline(output: dict[str, Any]) -> list[str]:
    aging = output.get("aging_type") if isinstance(output.get("aging_type"), dict) else {}
    client = output.get("client") if isinstance(output.get("client"), dict) else {}
    block = output.get("age_changes") if isinstance(output.get("age_changes"), dict) else {}
    type_id = str(aging.get("type_id") or "")
    text = _normalize_for_match(str(block.get("text") or ""))
    if not text:
        return ["age_changes missing"]

    errors: list[str] = []
    age_markers = re.findall(r"(?:\b\d{2}\s*-\s*\d{2}\b|после\s+\d{2})", text)
    if len(set(age_markers)) < 3:
        errors.append("age_changes must include three age stages, e.g. 25–30, 30–35 and после 40")
    if not any(marker.startswith("после") for marker in age_markers):
        errors.append("age_changes must include a 'после 40' stage")

    client_age = client.get("age")
    if isinstance(client_age, int):
        expected_markers = _expected_age_markers(client_age)
        if not any(marker in text for marker in expected_markers):
            errors.append("age_changes must be tied to the client's current/nearest age stage")

    combo_components = mixed_combo_type_ids_from_payload(output) if type_id == "tired_mixed" else []
    if type_id == "tired_mixed" and len(combo_components) > 1:
        missing_components = [
            MIXED_COMPONENT_NAMES.get(component_id, component_id)
            for component_id, markers in _combo_marker_sets(combo_components, AGE_CHANGE_REQUIRED_MARKERS)
            if not any(marker in text for marker in markers)
        ]
        if missing_components:
            errors.append("age_changes missing age dynamics for combo components: " + ", ".join(missing_components))
    elif type_id not in AGE_CHANGE_REQUIRED_MARKERS:
        errors.append(f"age_changes unknown aging type: {type_id or '<missing>'}")
    elif not any(marker in text for marker in AGE_CHANGE_REQUIRED_MARKERS[type_id]):
        errors.append(f"age_changes missing age dynamics for {type_id}")

    if not any(marker in text for marker in AGE_CHANGE_ACTION_MARKERS):
        errors.append("age_changes must end with a current motivational action")
    return errors


def validate_text_length(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for path, max_chars in TEXT_LIMITS.items():
        value = _get_path_values(output, path)
        for item_path, text in value:
            if len(text) > max_chars:
                errors.append(f"text too long: {item_path} > {max_chars}")
    for path, max_items in LIST_LIMITS.items():
        values = _get_path_values(output, path, include_lists=True)
        for item_path, value in values:
            if isinstance(value, list) and len(value) > max_items:
                errors.append(f"too many items: {item_path} > {max_items}")
    return errors


def _get_path_values(data: dict[str, Any], dotted_path: str, *, include_lists: bool = False) -> list[tuple[str, Any]]:
    parts = dotted_path.split(".")

    def walk(value: Any, remaining: list[str], path: str) -> list[tuple[str, Any]]:
        if not remaining:
            if include_lists or isinstance(value, str):
                return [(path, value)]
            return []
        head = remaining[0]
        tail = remaining[1:]
        if isinstance(value, dict):
            return walk(value.get(head), tail, f"{path}.{head}" if path else head)
        if isinstance(value, list):
            result: list[tuple[str, Any]] = []
            for index, item in enumerate(value):
                result.extend(walk(item, remaining, f"{path}[{index}]"))
            return result
        return []

    return walk(data, parts, "")


def validate_forecast_periods(output: dict[str, Any]) -> list[str]:
    forecast = output.get("time_forecast") if isinstance(output.get("time_forecast"), dict) else {}
    items = forecast.get("items") if isinstance(forecast.get("items"), list) else []
    if len(items) != 3:
        return ["forecast periods wrong: expected exactly 3 items"]
    errors: list[str] = []
    for index, expected in enumerate(FORECAST_PERIODS):
        item = items[index] if isinstance(items[index], dict) else {}
        if item.get("period") != expected:
            errors.append(f"forecast periods wrong: item {index + 1} must be '{expected}'")
        if len(str(item.get("text") or "")) > TEXT_LIMITS["time_forecast.items.text"]:
            errors.append(f"text too long: time_forecast.items[{index}].text > 90")
    return errors


def validate_bella_protocol_v4(output: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        output = normalize_protocol_v4_shape(output)
        output = validate_schema(output)
        output = canonicalize_knowledge_base_blocks(output)
        output = repair_protocol_v4_validation_edges(output)
        output = normalize_protocol_v4_lengths(output)
        output = validate_schema(output)
    except ProtocolValidationError as exc:
        errors.extend(exc.errors)
        raise ProtocolValidationError(errors) from exc
    validators = [
        validate_allowed_aging_type,
        validate_no_forbidden_phrases,
        validate_visual_age,
        validate_aging_consistency,
        validate_skin_type_structure,
        validate_face_strengths_concrete,
        validate_future_changes_from_knowledge,
        validate_age_changes_timeline,
        validate_no_copied_examples,
        validate_no_generic_template_text,
        validate_photo_specific_protocol,
        validate_text_length,
        validate_forecast_periods,
    ]
    for validator in validators:
        errors.extend(validator(output))
    if errors:
        raise ProtocolValidationError(errors)
    return output


def _clip_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", str(value or "")).strip()
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= max_chars:
        return text
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if part.strip()]
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*selected, sentence]).strip()
        if len(candidate) > max_chars:
            break
        selected.append(sentence)
    if selected:
        return " ".join(selected).strip(" .,:;—–-") + "."
    for separator in (". ", "; ", ": ", ", ", " — ", " - ", " – "):
        head = text.split(separator, 1)[0].strip(" .,:;—–-")
        if max(40, max_chars // 3) <= len(head) <= max_chars:
            return f"{head}."
    words: list[str] = []
    for word in text.split():
        candidate = " ".join([*words, word])
        if len(candidate) > max_chars:
            break
        words.append(word)
    while words and _normalize_for_match(words[-1]) in {"и", "а", "но", "в", "с", "к", "по", "для", "на", "о"}:
        words.pop()
    return (" ".join(words).strip(" .,:;—–-") or text[:max_chars].strip()).rstrip(".") + "."


def normalize_protocol_v4_lengths(output: dict[str, Any]) -> dict[str, Any]:
    result = dict(output)
    for path, max_chars in TEXT_LIMITS.items():
        _set_path_text(result, path, max_chars)
    for path, max_items in LIST_LIMITS.items():
        _trim_path_list(result, path, max_items)
    return result


def _set_path_text(data: Any, dotted_path: str, max_chars: int) -> None:
    parts = dotted_path.split(".")
    if not parts:
        return
    head, *tail = parts
    if isinstance(data, dict):
        if head not in data:
            return
        if tail:
            _set_path_text(data[head], ".".join(tail), max_chars)
        elif isinstance(data[head], str):
            data[head] = _clip_text(data[head], max_chars)
    elif isinstance(data, list):
        for item in data:
            _set_path_text(item, dotted_path, max_chars)


def _trim_path_list(data: Any, dotted_path: str, max_items: int) -> None:
    parts = dotted_path.split(".")
    if not parts:
        return
    head, *tail = parts
    if isinstance(data, dict):
        if head not in data:
            return
        if tail:
            _trim_path_list(data[head], ".".join(tail), max_items)
        elif isinstance(data[head], list):
            data[head] = data[head][:max_items]
    elif isinstance(data, list):
        for item in data:
            _trim_path_list(item, dotted_path, max_items)


def _type_from_partial(payload: dict[str, Any]) -> str:
    aging = payload.get("aging_type") if isinstance(payload.get("aging_type"), dict) else {}
    type_id = aging.get("type_id")
    if type_id in AGING_TYPE_NAMES:
        return type_id
    text = _normalize_for_match(_all_text(payload))
    scores = {type_id: _marker_count(text, markers) for type_id, markers in TYPE_MARKERS.items()}
    return max(scores, key=scores.get) if any(scores.values()) else "tired_mixed"


def fallback_protocol_v4_from_partial(
    payload: dict[str, Any] | None,
    *,
    user_name: str | None,
    user_age: int | None,
    selected_problems: list[str] | None = None,
) -> dict[str, Any]:
    raise ProtocolValidationError(["local template fallback is disabled; retry AI generation"])


def protocol_v4_to_legacy_payload(output: dict[str, Any]) -> dict[str, Any]:
    aging = output["aging_type"]
    aging_display_name = aging.get("display_name") or build_aging_type_display_name(aging["type_id"], aging.get("combo_type_ids", []))
    skin_visual_age = output["skin_visual_age"]
    skin_type = output["skin_type"]
    strengths = output["face_strengths"]
    future = output["future_changes"]
    age_changes = output["age_changes"]
    benefits = output["face_fitness_benefits"]
    forecast = output["time_forecast"]
    growth = output["growth_zones"]
    final = output["final_summary"]
    zones = []
    for zone in output["zone_map"]["zones"]:
        status = zone.get("status", "yellow")
        legacy_status = "good" if status == "green" else "priority" if status in {"orange", "red"} else "attention"
        zones.append(
            {
                "number": zone.get("number", len(zones) + 1),
                "name": zone.get("title", "Зона внимания"),
                "status": legacy_status,
                "color": "red" if status == "orange" else status,
                "short_comment": zone.get("meaning", ""),
                "reason": zone.get("meaning", ""),
                "recommended_focus": growth.get("summary", ""),
            }
        )

    forecast_items = forecast.get("items", [])
    forecast_texts = [f"{item.get('period')} — {item.get('text')}" for item in forecast_items if isinstance(item, dict)]
    while len(forecast_texts) < 3:
        forecast_texts.append("")

    return {
        "skin_visual_age": {
            "estimated_range": str(skin_visual_age["visual_age"]),
            "explanation": skin_visual_age["text"],
            "confidence": aging.get("confidence", "medium"),
            "passport_age": skin_visual_age["passport_age"],
            "visual_age": skin_visual_age["visual_age"],
            "age_delta": skin_visual_age["age_delta"],
            "age_delta_label": skin_visual_age["age_delta_label"],
        },
        "skin_type": {
            "type": skin_type.get("type_name", ""),
            "features": skin_type.get("bullets", []),
            "strengths": strengths.get("bullets", []),
            "attention_points": growth.get("items", []),
        },
        "face_type_and_aging_type": {
            "face_type": strengths.get("text", ""),
            "aging_type": aging_display_name,
            "explanation": aging.get("text", ""),
        },
        "zones": zones,
        "causes": [future.get("text", ""), age_changes.get("text", "")] + future.get("bullets", []),
        "strengths": strengths.get("bullets") or [strengths.get("text", "")],
        "facefitness_benefits": benefits.get("bullets") or [benefits.get("text", "")],
        "time_forecast": {
            "first_changes": forecast_texts[0],
            "visible_changes": forecast_texts[1],
            "stable_result": forecast_texts[2],
        },
        "summary": final.get("text", ""),
        "cta_recommendation": final.get("quote", ""),
        "journal_protocol": {
            "skin_age": {
                "age_value": skin_visual_age["visual_age"],
                "score_value": 82,
                "main_observation": skin_visual_age["text"],
                "what_affects_age_perception": growth.get("items", [])[:3],
                "main_focus": growth.get("summary", ""),
                "description": skin_visual_age["text"],
            },
            "skin_type": {
                "type_name": skin_type.get("type_name", ""),
                "description": skin_type.get("text", ""),
                "features": skin_type.get("bullets", []),
                "strength": (skin_type.get("bullets") or [""])[0],
                "care_focus": skin_type.get("text", ""),
            },
            "face_type": {
                "face_shape": strengths.get("text", ""),
                "aging_type": aging_display_name,
                "main_scenario": aging.get("text", ""),
                "what_appears_first": future.get("bullets", []),
                "recommended_start": growth.get("summary", ""),
                "base_note": strengths.get("text", ""),
            },
            "zone_map": {"zones": output["zone_map"]["zones"]},
            "why_happens": {"title": future.get("title", "Какие изменения будут со временем"), "main_explanation": future.get("text", ""), "mechanics": [], "conclusion": growth.get("summary", "")},
            "age_changes": age_changes,
            "strengths": {"title": strengths.get("title", "Ваши сильные стороны лица"), "items": [{"title": item, "why_it_is_strength": item, "how_to_enhance": benefits.get("text", "")} for item in strengths.get("bullets", [])]},
            "face_fitness_benefits": {"title": benefits.get("title", "Что даст фейс-фитнес"), "personal_sequence": [{"step": i + 1, "focus": item, "why_first": item, "expected_effect": item} for i, item in enumerate(benefits.get("bullets", []))], "conclusion": benefits.get("text", "")},
            "time_forecast": forecast,
            "growth_zones": growth,
            "final_summary": {"main_conclusion": final.get("text", ""), "quote": final.get("quote", "")},
        },
        "aging_classification": {
            "type_id": aging["type_id"],
            "type_name": aging["type_name"],
            "combined_label": aging_display_name if aging_display_name != aging["type_name"] else "",
            "combo_type_ids": aging.get("combo_type_ids", []),
            "combo_type_names": aging.get("combo_type_names", []),
            "confidence": aging.get("confidence", "medium"),
            "evidence_from_photo": aging.get("evidence", []),
            "kb_source_used": True,
        },
        "face_features": {
            "title": "Ваши сильные стороны лица",
            "description": strengths.get("text", ""),
            "items": [{"feature": item, "observation": item, "why_it_is_beautiful": item, "how_face_fitness_reveals_it": benefits.get("text", "")} for item in strengths.get("bullets", [])],
        },
        "aging_type_block": {"title": "Тип старения", "text": aging.get("text", ""), "characteristic": aging.get("text", ""), "how_changes_over_time": future.get("text", ""), "what_if_nothing_changes": age_changes.get("text", ""), "main_focus": growth.get("summary", "")},
    }
