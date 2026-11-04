"""Explicitly labelled sample knowledge; it is not an official college policy."""

DEMO_NOTICE = 'Демонстрационный пример; инструкция требует проверки колледжем.'

# These examples are made available only if the operator explicitly enables demo mode.
# Negative IDs do not collide with database records.
DEMO_KNOWLEDGE = [
    {'id': -1, 'question': 'Как подключить ноутбук к проектору?',
     'answer': DEMO_NOTICE + ' Если оборудование исправно, подключите подходящий внешний кабель между ноутбуком и проектором и выберите источник сигнала на проекторе. Если изображения нет, сообщите сотруднику.', 'is_verified': 1, 'source': DEMO_NOTICE},
    {'id': -2, 'question': 'Как сообщить о неисправности оборудования?',
     'answer': DEMO_NOTICE + ' Укажите место и опишите неисправность в форме, затем проверьте и отправьте заявку.', 'is_verified': 1, 'source': DEMO_NOTICE},
    {'id': -3, 'question': 'Как проверить статус своей заявки?',
     'answer': DEMO_NOTICE + ' Откройте личный кабинет и выберите свою заявку. Там отображаются статус и публичная переписка.', 'is_verified': 1, 'source': DEMO_NOTICE},
    {'id': -4, 'question': 'Что делать, если принтер не печатает?',
     'answer': DEMO_NOTICE + ' Убедитесь, что выбрали нужный принтер и в доступном лотке есть бумага. Не вскрывайте оборудование. Если проблема осталась, создайте заявку.', 'is_verified': 1, 'source': DEMO_NOTICE},
    {'id': -5, 'question': 'Как выбрать категорию заявки?',
     'answer': DEMO_NOTICE + ' Выберите категорию, наиболее подходящую к проблеме. Если не уверены, выберите «Другое» и опишите проблему.', 'is_verified': 1, 'source': DEMO_NOTICE},
]
