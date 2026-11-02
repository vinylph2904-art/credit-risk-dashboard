"""Fresh ocean palette with complementary teal, violet, and restrained coral accents."""
from math import isfinite


NAVY = '#263849'
BLUE = '#2f7be5'
BLUE_DEEP = '#245fa8'
BLUE_MEDIUM = '#56afe4'
CYAN = '#2db9d2'
TEAL = '#a8d6cc'
VIOLET = '#c9dcf6'
CORAL = '#dde3e8'
GREEN = '#16a37f'
AMBER = '#f2a93b'
ORANGE = '#f2784b'
RED = BLUE_DEEP  # Legacy chart token; emphasize risk with deep blue and labels.

MEDIUM = AMBER
ROSE = VIOLET
LIGHT = BLUE_MEDIUM
PALE = '#b9dff4'
FAINT = '#f0f7fc'
SURFACE = '#f5f8fb'
UNKNOWN = '#fff0d9'
SEQUENTIAL = [PALE, BLUE_MEDIUM, BLUE, BLUE_DEEP]
CATEGORICAL = [BLUE, TEAL, CYAN, VIOLET, CORAL]
NEUTRAL = '#677b8c'
NEUTRAL_LIGHT = '#b8d8eb'
DATA_ROSE = BLUE_MEDIUM
COMPARISON_GRAY = '#b8d8eb'


def _scale_values(values, pale, strong):
    numbers = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float('nan')
        numbers.append(number if isfinite(number) and number >= 0 else None)
    maximum = max((value for value in numbers if value is not None), default=0)
    colors = []
    for value in numbers:
        if value is None:
            colors.append(UNKNOWN)
            continue
        fraction = value / maximum if maximum else 0
        rgb = [round(low + (high - low) * fraction) for low, high in zip(pale, strong)]
        colors.append('#' + ''.join(f'{channel:02x}' for channel in rgb))
    return colors


def value_red_colors(values):
    """Use blue context and use deep blue for the largest observed risk value."""
    values = list(values)
    colors = value_blue_colors(values)
    numbers = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float('nan')
        numbers.append(number if isfinite(number) and number >= 0 else None)
    maximum = max((number for number in numbers if number is not None), default=0)
    return [RED if maximum > 0 and number == maximum else color
            for number, color in zip(numbers, colors)]


def value_blue_colors(values):
    """Scale normal values from pale blue to the primary blue."""
    return _scale_values(values, (185, 223, 244), (47, 123, 229))


def categorical_colors(count):
    return [CATEGORICAL[index % len(CATEGORICAL)] for index in range(count)]
