# test.py
from rusprofile_api import get_entity_by_inn

# Тест ИП
print("=== ИП Малётин ===")
result = get_entity_by_inn("732815880648")
for k, v in result.items():
    print(f"  {k}: {v}")

# Тест юрлицо
print("\n=== Сбербанк ===")
result2 = get_entity_by_inn("7707083893")
for k, v in result2.items():
    print(f"  {k}: {v}")

# Тест несуществующий ИНН
print("\n=== Несуществующий ИНН ===")
try:
    get_entity_by_inn("0000000000")
except Exception as e:
    print(f"  Ожидаемая ошибка: {e}")