class MathUtils:
    """Утилиты для математических расчетов."""

    @staticmethod
    def safe_float(value, default=None):
        """Безопасное преобразование строки в float."""
        if value is None: return default
        if isinstance(value, (float, int)): return float(value)
        try:
            return float(str(value).strip().replace(',', '.'))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def linear_interpolate(pairs, target_x):
        """
        Линейная интерполяция значения Y для target_x по списку пар [(x, y), ...].
        Не выполняет экстраполяцию (возвращает None).
        """
        if not pairs: return None

        # Сортировка пар по X
        sorted_pairs = sorted(pairs, key=lambda p: p[0])

        # Проверка границ
        if target_x < sorted_pairs[0][0] or target_x > sorted_pairs[-1][0]:
            return None  # Экстраполяция запрещена или невозможна

        # Точное совпадение
        for x, y in sorted_pairs:
            if x == target_x: return y

        # Поиск интервала
        for i in range(len(sorted_pairs) - 1):
            x1, y1 = sorted_pairs[i]
            x2, y2 = sorted_pairs[i + 1]
            if x1 < target_x < x2:
                if x2 - x1 == 0: return y1
                return y1 + (target_x - x1) * (y2 - y1) / (x2 - x1)

        return None