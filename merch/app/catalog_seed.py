"""Стартовый каталог — тот же, что в прототипе (SEED из hallmarksuite.tsx).

Отличия от прототипа:
  * все изделия, цвета и площадки включены (on=True), чтобы модуль работал
    сразу после развёртывания — в прототипе они выключены и включаются
    вручную в модуле Configuration;
  * фотографии изделий (base64 в прототипе) не переносятся — поле img
    поддерживается (URL картинки) и заполняется через PUT /api/catalog.

Каталог редактируется администратором через API; структура записи:
  types[]:  name, on, sheet (a5|a7|a8), site (индекс площадки или None),
            edition (тираж), colors[]: name, hex, on, img
  places[]: name, on
"""

SEED_CATALOG = {
    "types": [
        {
            "name": "Balloon Cat", "on": True, "sheet": "a5", "site": 0, "edition": 500,
            "colors": [
                {"name": "Purple chrome", "hex": "#5B2483", "on": True, "img": None},
                {"name": "Burgundy chrome", "hex": "#8C1F3D", "on": True, "img": None},
                {"name": "Gold", "hex": "#C98A22", "on": True, "img": None},
                {"name": "Matte black", "hex": "#33343A", "on": True, "img": None},
                {"name": "Matte white", "hex": "#EFEDE8", "on": True, "img": None},
            ],
        },
        {
            "name": "Guardian of Cyprus", "on": True, "sheet": "a8", "site": 1, "edition": 500,
            "colors": [
                {"name": "Grey", "hex": "#7C7A74", "on": True, "img": None},
            ],
        },
        {
            "name": "Guardian of Cyprus S", "on": True, "sheet": "a8", "site": 1, "edition": 500,
            "colors": [
                {"name": "Grey", "hex": "#7C7A74", "on": True, "img": None},
            ],
        },
    ],
    "places": [
        {"name": "Dubai", "on": True},
        {"name": "Cyprus", "on": True},
    ],
}

SEED_CERTIFICATE = {
    "brand": "CATALIST",
    "issuer": "",
    "role": "",
    "verifyUrl": "https://code.catalist.world",
}
