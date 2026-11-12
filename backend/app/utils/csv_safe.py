"""Make a value safe to write into a CSV that someone opens in a spreadsheet."""

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Prefix a string that begins with a formula character with a single quote.

    Non-strings (numbers, None) are returned unchanged.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def csv_safe_row(row):
    return [csv_safe(cell) for cell in row]


class SafeWriter:
    """A csv.writer whose rows go through csv_safe."""

    def __init__(self, fileobj):
        import csv
        self._writer = csv.writer(fileobj)

    def writerow(self, row):
        return self._writer.writerow(csv_safe_row(row))
