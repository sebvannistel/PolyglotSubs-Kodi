# -*- coding: utf-8 -*-

__irregularOrdinals = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}

__tens = [
    None, None, "twenty", "thirty", "forty",
    "fifty", "sixty", "seventy", "eighty", "ninety"
]

__small = [
    "zero", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen"
]

__huge = [None, None] + [h + "illion" for h in ("m", "b", "tr", "quadr", "quint", "sext", "sept", "oct", "non", "dec")]

def __nonzero(c, n, connect=''):
    """
    Handles non-zero numbers.

    Args:
        c (str): The character to connect with.
        n (int): The number.
        connect (str, optional): The connection string. Defaults to ''.

    Returns:
        str: The string representation of the number.
    """
    return "" if n == 0 else connect + c + __spell_integer(n)

def __last_and(num):
    """
    Adds 'and' to the last part of a number string.

    Args:
        num (str): The number string.

    Returns:
        str: The number string with 'and' added.
    """
    if ',' in num:
        pre, last = num.rsplit(',', 1)
        if ' and ' not in last:
            last = ' and' + last
        num = ''.join([pre, ',', last])
    return num

def __big(e, n):
    """
    Handles big numbers.

    Args:
        e (int): The exponent.
        n (int): The number.

    Returns:
        str: The string representation of the number.
    """
    if e == 0:
        return __spell_integer(n)
    elif e == 1:
        return __spell_integer(n) + " thousand"
    else:
        return __spell_integer(n) + " " + __huge[e]

def __base1000_rev(n):
    """
    Generator for base 1000 representation of a number.

    Args:
        n (int): The number.

    Yields:
        int: The next part of the number.
    """
    while n != 0:
        n, r = divmod(n, 1000)
        yield r

def __spell_integer(n):
    """
    Spells out an integer.

    Args:
        n (int): The integer to spell out.

    Returns:
        str: The spelled out integer.
    """
    if n < 0:
        return "minus " + __spell_integer(-n)
    elif n < 20:
        return __small[n]
    elif n < 100:
        a, b = divmod(n, 10)
        return __tens[a] + __nonzero("-", b)
    elif n < 1000:
        a, b = divmod(n, 100)
        return __small[a] + " hundred" + __nonzero(" ", b, ' and')
    else:
        num = ", ".join([__big(e, x) for e, x in
                         enumerate(__base1000_rev(n)) if x][::-1])
        return __last_and(num)

def convert(n):
    """
    Converts a number to its ordinal representation.

    Args:
        n (int or str): The number to convert.

    Returns:
        str: The ordinal representation of the number.
    """
    conversion = int(float(n))
    num = __spell_integer(conversion)
    hyphen = num.rsplit("-", 1)
    num = num.rsplit(" ", 1)
    delim = " "
    if len(num[-1]) > len(hyphen[-1]):
        num = hyphen
        delim = "-"

    if num[-1] in __irregularOrdinals:
        num[-1] = delim + __irregularOrdinals[num[-1]]
    elif num[-1].endswith("y"):
        num[-1] = delim + num[-1][:-1] + "ieth"
    else:
        num[-1] = delim + num[-1] + "th"
    return "".join(num)
