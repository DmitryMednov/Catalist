"""Стартовый каталог — линейка запуска, согласованная заказчиком.

Отличия от прототипа (SEED из hallmarksuite.tsx):
  * все изделия, цвета и площадки включены (on=True), чтобы модуль работал
    сразу после развёртывания — в прототипе они включаются вручную;
  * вместо base64-фотографий поле img хранит URL — фотографии из прототипа
    вынесены в merch/web/products/ и раздаются как /static/products/*;
  * цвет «Crystal White» заменил «Matte white» из прототипа (решение
    заказчика, сентябрь 2026), фотография пока от белой фигурки прототипа;
  * форматы сертификатов — по требованию заказчика: Balloon Cat A5,
    Guardian of Cyprus A7, Guardian of Cyprus S A8.

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
                {"name": "Purple Chrome", "hex": "#5B2483", "on": True,
                 "img": "/static/products/balloon-cat-purple.jpg"},
                {"name": "Burgundy Chrome", "hex": "#8C1F3D", "on": True,
                 "img": "/static/products/balloon-cat-burgundy.jpg"},
                {"name": "Gold", "hex": "#C98A22", "on": True,
                 "img": "/static/products/balloon-cat-gold.jpg"},
                {"name": "Matte Black", "hex": "#33343A", "on": True,
                 "img": "/static/products/balloon-cat-black.jpg"},
                {"name": "Crystal White", "hex": "#EFEDE8", "on": True,
                 "img": "/static/products/balloon-cat-crystal.jpg"},
            ],
        },
        {
            "name": "Guardian of Cyprus", "on": True, "sheet": "a7", "site": 1, "edition": 500,
            "colors": [
                {"name": "Grey", "hex": "#7C7A74", "on": True,
                 "img": "/static/products/guardian.jpg"},
            ],
        },
        {
            "name": "Guardian of Cyprus S", "on": True, "sheet": "a8", "site": 1, "edition": 500,
            "colors": [
                {"name": "Grey", "hex": "#7C7A74", "on": True,
                 "img": "/static/products/guardian-s.jpg"},
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
