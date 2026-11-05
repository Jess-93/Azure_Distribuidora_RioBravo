import csv
import re
import secrets
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED_COLUMNS = {
    "sku",
    "producto",
    "presentacion",
    "aliases",
    "existencia_disponible",
    "unidad",
    "actualizado",
}
IGNORED_QUERY_WORDS = {
    "a", "al", "con", "cuanto", "cuanta", "cuantos", "cuantas", "dame", "darme",
    "de", "del", "el", "en", "favor", "hay", "la", "las", "lo", "los", "me", "mi",
    "nos", "por", "puedes", "queda", "quedan", "quedo", "que", "rio", "tenemos",
    "tiene", "tienen", "un", "una", "uno", "unos", "unas", "y", "o",
    "disponible", "existencia", "existencias", "inventario", "almacen", "bodega",
    "precio", "precios", "costo", "costos", "cuesta", "cuestan",
    "vale", "valen", "valor", "valores",
}
NON_DISTINCTIVE_QUERY_WORDS = {
    "cm", "gr", "gramo", "gramos", "kg", "kilo", "kilos", "litro", "litros",
    "ml", "pieza", "piezas", "unidad", "unidades",
}
FUZZY_WORD_MIN_LENGTH = 5
FUZZY_WORD_MAX_DISTANCE = 1
RANKING_LIMIT_MAX = 50
RANKING_COUNT_WORDS = {
    "uno": 1, "una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "quince": 15, "veinte": 20,
}
RANDOM_WORDS = {"azar", "aleatorio", "aleatoria", "aleatorios", "aleatorias", "random"}
RANKING_UNITS = {
    "pieza": "piezas",
    "piezas": "piezas",
    "paquete": "paquetes",
    "paquetes": "paquetes",
    "juego": "juegos",
    "juegos": "juegos",
}
INVENTORY_LIST_WORDS = {
    "catalogo", "lista", "listado", "listar", "todo", "toda", "todos", "todas",
    "total", "completo", "completa", "completos", "completas",
}
INVENTORY_DOMAIN_WORDS = {
    "catalogo", "existencia", "existencias", "inventario", "stock", "sku",
    "codigo", "codigos", "producto", "productos", "mercancia", "mercancias",
    "articulo", "articulos", "mercaderia", "mercaderias", "precio", "precios",
}
INVENTORY_HELP_PATTERNS = (
    r"^\s*(?:hola\s+)?(?:en\s+)?que\s+(?:me\s+)?puedes\s+ayudar(?:me)?\s*[!.?]*\s*$",
    r"^\s*(?:hola\s+)?que\s+puedes\s+hacer\s*[!.?]*\s*$",
    r"^\s*para\s+que\s+sirves\s*[!.?]*\s*$",
    r"^\s*que\s+(?:tipo\s+de\s+)?consultas?\s+puedo\s+hacer\s*[!.?]*\s*$",
    r"^\s*que\s+sabes\s+hacer\s*[!.?]*\s*$",
    r"^\s*(?:necesito|quiero)\s+ayuda\s*[!.?]*\s*$",
)
PRICE_QUERY_WORDS = {
    "precio", "precios", "costo", "costos", "cuesta", "cuestan",
    "vale", "valen", "valor", "valores",
}
SKU_SPEECH_VARIANTS = {
    "sku", "skus", "sq", "scu", "scuare", "skaw", "skew", "escu", "esku",
    "eski", "eskiu", "esqui", "esqu", "esquiu", "square", "squares",
    "skuer", "skueres", "squ", "skup",
}
SKU_SPEECH_PREFIX_PATTERN = re.compile(
    r"\b(?:"
    r"ese\s+(?:cu|ka\s+u|ca\s+u|k\s+u|que(?:\s+u)?|q\s+u|kiu)|"
    r"es\s+(?:cu|ka\s+u|ca\s+u|k\s+u|que(?:\s+u)?|q\s+u|kiu)|"
    r"s\s*(?:k|q)?\s*u?p?|"
    r"sc?u|"
    r"sku|skus|skup|squ|sque|sq|scu|scue|scuare|skaw|skew|escu|esku|eski|eskiu|esqui|esqu|esquiu|"
    r"square|squares|skuer|skueres"
    r")\b"
)
SKU_QUERY_CONTEXT_WORDS = IGNORED_QUERY_WORDS | {
    "busca", "buscar", "buscame", "dame", "dime", "indica", "indicar",
    "muestra", "mostrar", "consulta", "consultar", "codigo", "codigos",
    "numero", "numeros", "clave", "claves", "producto", "productos",
    "articulo", "articulos", "equis", "x", "es", "este", "favor",
    "ok", "lista", "listado", "todo", "toda", "todos", "todas",
    "completo", "completa", "completos", "completas",
    "enviar", "envia", "manda", "mandar", "mandame", "mensaje",
    "corresponde", "presentacion", "fecha", "actualizacion",
}
SPOKEN_NUMBER_VALUES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3,
    "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100,
    "ciento": 100, "doscientos": 200, "trescientos": 300, "cuatrocientos": 400,
    "quinientos": 500, "seiscientos": 600, "setecientos": 700,
    "ochocientos": 800, "novecientos": 900,
}
SPOKEN_NUMBER_WORDS = set(SPOKEN_NUMBER_VALUES) | {"mil", "y"}


class InventoryFileError(ValueError):
    pass


def normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")


def normalize_inventory_words(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", normalized_text(value))
    normalized_words = {
        word[:-1] if len(word) > 4 and word.endswith("s") else word
        for word in words
    }
    return normalized_words - IGNORED_QUERY_WORDS


def parse_spoken_sku_number(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    if all(token.isdigit() for token in tokens):
        return "".join(tokens)
    if any(token.isdigit() or token not in SPOKEN_NUMBER_WORDS for token in tokens):
        return None

    spoken_digits = [SPOKEN_NUMBER_VALUES[token] for token in tokens if token in SPOKEN_NUMBER_VALUES]
    if tokens and all(token in SPOKEN_NUMBER_VALUES for token in tokens) and all(
        value < 10 for value in spoken_digits
    ):
        return "".join(str(value) for value in spoken_digits)

    total = 0
    current = 0
    for token in tokens:
        if token == "y":
            continue
        if token == "mil":
            total += max(current, 1) * 1000
            current = 0
        elif token in SPOKEN_NUMBER_VALUES:
            value = SPOKEN_NUMBER_VALUES[token]
            if value >= 100:
                current = max(current, 1) * value
            else:
                current += value
        else:
            return None
    return str(total + current)


def spoken_sku_number(query: str) -> str | None:
    normalized_query = normalized_text(query)
    normalized_query = re.sub(r"\bskamil\b", "sku mil", normalized_query)
    prefix_matches = list(SKU_SPEECH_PREFIX_PATTERN.finditer(normalized_query))
    has_sku_prefix = len(prefix_matches) == 1
    if len(prefix_matches) > 1:
        return None

    words = re.findall(r"[a-z0-9]+", normalized_query)
    has_sku_context = bool(set(words) & {
        "inventario", "existencia", "existencias", "stock", "producto", "productos",
        "codigo", "codigos", "numero", "numeros", "clave", "claves",
    })
    if not has_sku_prefix and not has_sku_context:
        return None

    query_for_numbers = (
        SKU_SPEECH_PREFIX_PATTERN.sub(" ", normalized_query, count=1)
        if has_sku_prefix
        else normalized_query
    )
    tokens = re.findall(r"[a-z0-9]+", query_for_numbers)
    number_tokens = [token for token in tokens if token.isdigit() or token in SPOKEN_NUMBER_WORDS]
    other_tokens = set(tokens) - set(number_tokens)
    allowed_context = SKU_QUERY_CONTEXT_WORDS | {
        "inventario", "existencia", "existencias", "stock", "almacen", "bodega",
        "k", "solo", "informacion", "detalle", "nombre", "producto", "presentacion",
        "formato", "fecha", "actualizado", "actualizada", "precio", "precios",
        "costo", "costos", "cuesta", "cuestan", "valor", "valores",
        "disponible", "cantidad",
    }
    if not number_tokens or not other_tokens <= allowed_context:
        return None
    return parse_spoken_sku_number(number_tokens)


def normalize_inventory_query(query: str) -> str:
    normalized_query = normalized_text(query)
    prefix_matches = list(SKU_SPEECH_PREFIX_PATTERN.finditer(normalized_query))
    if len(prefix_matches) != 1:
        return query

    sku_number = spoken_sku_number(query)
    if sku_number is None:
        return query

    prefix_match = prefix_matches[0]
    suffix = normalized_query[prefix_match.end():]
    number_tokens = []
    number_end = None
    for token_match in re.finditer(r"[a-z0-9]+", suffix, re.IGNORECASE):
        token = normalized_text(token_match.group())
        if token.isdigit() or token in SPOKEN_NUMBER_WORDS:
            number_tokens.append(token)
            number_end = prefix_match.end() + token_match.end()
            continue
        if not number_tokens and token in {"numero", "n"}:
            continue
        break

    if not number_tokens or number_end is None:
        return query

    parsed_number = parse_spoken_sku_number(number_tokens)
    if parsed_number is None or parsed_number.lstrip("0") != sku_number.lstrip("0"):
        return query

    return f"{query[:prefix_match.start()]}SKU-{sku_number}{query[number_end:]}"


def is_spoken_sku_request(query: str) -> bool:
    normalized_query = re.sub(r"\bskamil\b", "sku mil", normalized_text(query))
    words = re.findall(r"[a-z0-9]+", normalized_query)
    if SKU_SPEECH_PREFIX_PATTERN.search(normalized_query):
        return True

    has_inventory_context = bool(set(words) & {
        "inventario", "existencia", "existencias", "stock", "producto", "productos",
        "codigo", "codigos", "numero", "numeros", "clave", "claves",
    })
    has_digit = any(word.isdigit() for word in words)
    return has_inventory_context and has_digit


def inventory_help_requested(query: str) -> bool:
    normalized_query = re.sub(r"[^a-z0-9\s]", "", normalized_text(query)).strip()
    if normalized_query == "ayuda":
        return True
    return any(re.search(pattern, normalized_query) for pattern in INVENTORY_HELP_PATTERNS)


def inventory_greeting_requested(query: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", normalized_text(query)))
    greetings = {
        "hola",
        "saludos",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
    }
    normalized_query = " ".join(re.findall(r"[a-z0-9]+", normalized_text(query)))
    return normalized_query in greetings or words == {"hola"}


def inventory_price_requested(query: str) -> bool:
    return bool(set(re.findall(r"[a-z0-9]+", normalized_text(query))) & PRICE_QUERY_WORDS)


def requested_inventory_fields(query: str) -> list[str]:
    normalized_query = normalized_text(query)
    words = set(re.findall(r"[a-z0-9]+", normalized_query))
    fields = []

    if words & PRICE_QUERY_WORDS:
        fields.append("priceMxn")
    if words & {"fecha", "actualizacion", "actualizado", "actualizada"}:
        fields.append("updatedAt")
    if (
        words & {"existencia", "existencias", "inventario", "stock", "cantidad", "disponible"}
        or re.search(r"\b(?:cuanto|cuanta|cuantos|cuantas)\b", normalized_query)
    ):
        fields.append("available")
    if re.search(
        r"\b(?:cual|que|dime|indica|muestra|solo|quiero saber|necesito saber)\s+"
        r"(?:es\s+)?(?:el\s+)?(?:producto|nombre)\b",
        normalized_query,
    ):
        fields.append("product")
    if words & {"presentacion", "formato"}:
        fields.append("presentation")
    if re.search(
        r"\b(?:cual|que|dame|dime|indica|muestra|necesito saber|quiero saber)\s+"
        r"(?:es\s+)?(?:el\s+)?(?:sku|codigo|numero de inventario)\b"
        r"|\bsolo\s+(?:el\s+)?(?:sku|codigo)\b",
        normalized_query,
    ):
        fields.append("sku")
    if re.search(
        r"\b(?:tiene|hay|existe|esta)\s+(?:el\s+)?(?:sku|producto|articulo)\b"
        r"|\b(?:esta|se encuentra)\s+(?:registrado|en el inventario)\b",
        normalized_query,
    ):
        fields.append("exists")

    return fields


def inventory_item(row: dict, include_price: bool = False) -> dict:
    item = {
        "sku": row["sku"],
        "product": row["product"],
        "presentation": row["presentation"],
        "available": row["available"],
        "unit": row["unit"],
        "updatedAt": row["updatedAt"],
    }
    if include_price and row.get("priceMxn"):
        item["priceMxn"] = row["priceMxn"]
    return item


def requested_count(words: list[str], default: int) -> int:
    count_words = [
        word for word in words
        if (word.isdigit() and int(word) >= 1)
        or word in RANKING_COUNT_WORDS
    ]
    explicit_count_words = [
        word for word in count_words
        if word not in {"un", "una", "uno"}
    ]
    selected_word = next(iter(explicit_count_words or count_words), None)
    if selected_word is None:
        return default
    count = int(selected_word) if selected_word.isdigit() else RANKING_COUNT_WORDS[selected_word]
    return min(count, RANKING_LIMIT_MAX)


def random_inventory_selection(
    query: str,
    rows: list[dict],
    include_price: bool = False,
) -> dict | None:
    words = re.findall(r"[a-z0-9]+", normalized_text(query))
    if not RANDOM_WORDS.intersection(words):
        return None

    count = requested_count(words, default=5)
    selected_rows = secrets.SystemRandom().sample(rows, k=min(count, len(rows)))
    result = {
        "status": "random_selection",
        "items": [
            inventory_item(row, include_price)
            for row in selected_rows
        ],
    }
    if include_price:
        result["priceRequested"] = True
    return result


def inventory_ranking_limit(query: str) -> int | None:
    words = re.findall(r"[a-z0-9]+", normalized_text(query))
    ranking_words = {"top", "ranking", "mayor", "mayores", "maximo", "maxima", "mas"}
    inventory_words = {
        "existencia", "existencias", "inventario", "stock", "codigo", "codigos",
        "sku", "producto", "productos", "unidad", "unidades", "cantidad",
    }
    if not ranking_words.intersection(words) or not inventory_words.intersection(words):
        return None

    if any(
        (word.isdigit() and 1 <= int(word) <= RANKING_LIMIT_MAX)
        or word in RANKING_COUNT_WORDS
        for word in words
    ):
        return requested_count(words, default=1)
    if "codigos" in words or "productos" in words or "mayores" in words:
        return 10
    return 1


def inventory_price_ranking_limit(query: str) -> int | None:
    words = re.findall(r"[a-z0-9]+", normalized_text(query))
    ranking_words = {"top", "ranking", "mayor", "mayores", "maximo", "maxima", "mas"}
    if not PRICE_QUERY_WORDS.intersection(words) or not ranking_words.intersection(words):
        return None
    return requested_count(words, default=10)


def inventory_list_requested(query: str) -> bool:
    words = {
        word[:-1] if len(word) > 4 and word.endswith("s") else word
        for word in re.findall(r"[a-z0-9]+", normalized_text(query))
    }
    has_list_intent = bool(words & INVENTORY_LIST_WORDS)
    has_inventory_intent = bool(words & (INVENTORY_DOMAIN_WORDS | SKU_SPEECH_VARIANTS))
    has_ranking_intent = bool(words & {"top", "ranking", "mayor", "mayores", "maximo", "maxima", "mas"})
    return has_list_intent and has_inventory_intent and not has_ranking_intent


def inventory_multiple_matches(
    query: str,
    rows: list[dict],
    include_price: bool = False,
) -> dict | None:
    normalized_query = normalized_text(query)
    if len(requested_inventory_fields(query)) > 1:
        return None
    if not re.search(r"[,;]|\b(?:y|e|tambien)\b", normalized_query):
        return None

    query_words = normalize_inventory_words(query)
    if len(query_words) < 2:
        return None

    matched_groups = []
    matched_words = set()
    for query_word in sorted(query_words):
        if query_word.isdigit() or query_word in NON_DISTINCTIVE_QUERY_WORDS:
            continue
        exact = [row for row in rows if query_word in row["words"]]
        candidates = exact
        closest = False
        if not candidates and len(query_word) >= FUZZY_WORD_MIN_LENGTH:
            distances = [
                (word_distance(query_word, inventory_word), row)
                for row in rows
                for inventory_word in row["words"]
                if abs(len(query_word) - len(inventory_word)) <= FUZZY_WORD_MAX_DISTANCE
            ]
            best_distance = min((distance for distance, _ in distances), default=None)
            if best_distance is not None and best_distance <= FUZZY_WORD_MAX_DISTANCE:
                candidates = [row for distance, row in distances if distance == best_distance]
                closest = True
        if candidates:
            unique_candidates = {row["sku"]: row for row in candidates}
            matched_words.add(query_word)
            matched_groups.append({
                "term": query_word,
                "closest": closest,
                "items": [
                    inventory_item(row, include_price)
                    for row in list(unique_candidates.values())[:10]
                ],
            })

    if len(matched_words) < 2:
        return None
    result = {
        "status": "multiple_matches",
        "matches": matched_groups,
        "unmatched": sorted(query_words - matched_words),
    }
    if include_price:
        result["priceRequested"] = True
    return result


def inventory_list(rows: list[dict], include_price: bool = False) -> dict:
    grouped_rows = {}
    for row in rows:
        unit = RANKING_UNITS.get(normalized_text(row["unit"]), row["unit"].strip().lower())
        grouped_rows.setdefault(unit, []).append(row)

    groups = []
    for unit in sorted(grouped_rows):
        unit_rows = sorted(grouped_rows[unit], key=lambda row: row["sku"].casefold())
        total = sum((Decimal(row["available"]) for row in unit_rows), Decimal("0"))
        groups.append({
            "unit": unit,
            "total": format(total, "f"),
            "count": len(unit_rows),
            "items": [inventory_item(row, include_price) for row in unit_rows],
        })
    result = {"status": "inventory_list", "groups": groups}
    if include_price:
        result["priceRequested"] = True
    return result


def inventory_ranking(
    rows: list[dict],
    limit: int,
    include_price: bool = False,
    by_price: bool = False,
) -> dict:
    if by_price:
        ranked_rows = sorted(
            (row for row in rows if row.get("priceMxn")),
            key=lambda row: (-Decimal(row["priceMxn"]), row["sku"].casefold()),
        )[:limit]
        if not ranked_rows:
            return {"status": "no_prices"}
        result = {
            "status": "ranking",
            "limit": limit,
            "rankingBy": "price",
            "groups": [{
                "unit": "productos",
                "items": [inventory_item(row, include_price) for row in ranked_rows],
            }],
            "priceRequested": True,
        }
        return result

    groups_by_unit = {}
    for row in rows:
        unit = RANKING_UNITS.get(normalized_text(row["unit"]), row["unit"].strip().lower())
        groups_by_unit.setdefault(unit, []).append(row)

    groups = []
    for unit in sorted(groups_by_unit):
        sorted_rows = sorted(
            groups_by_unit[unit],
            key=lambda row: (-Decimal(row["available"]), row["sku"].casefold()),
        )
        cutoff = Decimal(sorted_rows[min(limit, len(sorted_rows)) - 1]["available"])
        items = [
            inventory_item({**row, "unit": unit}, include_price)
            for row in sorted_rows
            if Decimal(row["available"]) >= cutoff
        ]
        groups.append({"unit": unit, "items": items})

    result = {"status": "ranking", "limit": limit, "groups": groups}
    if include_price:
        result["priceRequested"] = True
    return result


def word_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous_row = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current_row = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current_row.append(min(
                current_row[-1] + 1,
                previous_row[right_index] + 1,
                previous_row[right_index - 1] + (left_character != right_character),
            ))
        previous_row = current_row
    return previous_row[-1]


def validate_updated_at(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False


def load_inventory(csv_path: Path) -> list[dict]:
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as inventory_file:
            reader = csv.DictReader(inventory_file)
            columns = {column.strip().lower() for column in (reader.fieldnames or [])}
            missing_columns = REQUIRED_COLUMNS - columns
            if missing_columns:
                raise InventoryFileError(
                    "El CSV de inventario no tiene todas las columnas requeridas."
                )

            rows = []
            seen_skus = set()
            for line_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    raise InventoryFileError(
                        f"La fila {line_number} del inventario tiene columnas de más."
                    )
                row = {
                    (key or "").strip().lower(): (value or "").strip()
                    for key, value in raw_row.items()
                }
                sku = row.get("sku", "")
                product = row.get("producto", "")
                presentation = row.get("presentacion", "")
                unit = row.get("unidad", "")
                quantity_value = row.get("existencia_disponible", "")
                updated_at = row.get("actualizado", "")
                if not all((sku, product, presentation, unit, quantity_value, updated_at)):
                    raise InventoryFileError(
                        f"Faltan datos obligatorios en la fila {line_number} del inventario."
                    )
                if sku in seen_skus:
                    raise InventoryFileError(f"El SKU {sku} está duplicado en el inventario.")
                seen_skus.add(sku)

                try:
                    quantity = Decimal(quantity_value)
                except InvalidOperation as error:
                    raise InventoryFileError(
                        f"La existencia del SKU {sku} no es un número válido."
                    ) from error
                if not quantity.is_finite() or quantity < 0:
                    raise InventoryFileError(
                        f"La existencia del SKU {sku} debe ser un número no negativo."
                    )
                if not validate_updated_at(updated_at):
                    raise InventoryFileError(
                        f"La fecha de actualización del SKU {sku} no es válida."
                    )
                price_value = row.get("precio_mxn", "")
                price = None
                if price_value:
                    try:
                        price = Decimal(price_value)
                    except InvalidOperation as error:
                        raise InventoryFileError(
                            f"El precio del SKU {sku} no es un número válido."
                        ) from error
                    if not price.is_finite() or price < 0:
                        raise InventoryFileError(
                            f"El precio del SKU {sku} debe ser un número no negativo."
                        )

                aliases = row.get("aliases", "")
                searchable_text = " ".join((sku, product, presentation, aliases.replace(";", " ")))
                rows.append({
                    "sku": sku,
                    "product": product,
                    "presentation": presentation,
                    "available": format(quantity, "f"),
                    "unit": unit,
                    "updatedAt": updated_at,
                    "priceMxn": format(price, "f") if price is not None else "",
                    "aliases": aliases,
                    "words": normalize_inventory_words(searchable_text),
                })
    except FileNotFoundError as error:
        raise InventoryFileError("No se encontró el archivo CSV de inventario.") from error
    except UnicodeDecodeError as error:
        raise InventoryFileError("El CSV de inventario debe estar guardado como UTF-8.") from error
    except OSError as error:
        raise InventoryFileError("No se pudo leer el archivo CSV de inventario.") from error
    except csv.Error as error:
        raise InventoryFileError("El archivo CSV de inventario no tiene un formato válido.") from error

    if not rows:
        raise InventoryFileError(
            "El CSV todavía no contiene productos. Agrega los SKU y existencias antes de consultar."
        )

    return rows


def list_inventory(csv_path: Path) -> list[dict]:
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"words", "priceMxn"}
        }
        for row in load_inventory(csv_path)
    ]


def search_inventory(query: str, csv_path: Path) -> dict:
    query = normalize_inventory_query(query)
    if inventory_help_requested(query):
        return {"status": "help"}
    if inventory_greeting_requested(query):
        return {"status": "greeting"}

    include_price = inventory_price_requested(query)
    price_ranking_limit = inventory_price_ranking_limit(query)
    if price_ranking_limit is not None:
        return inventory_ranking(
            load_inventory(csv_path),
            price_ranking_limit,
            include_price=True,
            by_price=True,
        )
    ranking_limit = inventory_ranking_limit(query)
    if ranking_limit is not None:
        return inventory_ranking(load_inventory(csv_path), ranking_limit, include_price)
    rows = load_inventory(csv_path)
    requested_fields = requested_inventory_fields(query)
    random_selection = random_inventory_selection(query, rows, include_price)
    if random_selection is not None:
        return random_selection
    if inventory_list_requested(query):
        return inventory_list(rows, include_price)

    multiple_matches = inventory_multiple_matches(query, rows, include_price)
    if multiple_matches is not None:
        return multiple_matches

    if is_spoken_sku_request(query):
        sku_number = spoken_sku_number(query)
        if sku_number is None:
            return {"status": "not_found"}
        sku_matches = [
            row for row in rows
            if (sku_digits := re.search(r"(\d+)$", row["sku"]))
            and sku_digits.group(1).lstrip("0") == sku_number.lstrip("0")
        ]
        if not sku_matches:
            return {"status": "not_found"}
        if len(sku_matches) > 1:
            result = {
                "status": "ambiguous",
                "candidates": [
                    inventory_item(row, include_price)
                    for row in sku_matches[:10]
                ],
            }
            if include_price:
                result["priceRequested"] = True
            return result
        result = {
            "status": "found",
            "item": inventory_item(sku_matches[0], include_price),
        }
        if include_price:
            result["priceRequested"] = True
        if requested_fields:
            result["requestedFields"] = requested_fields
        return result

    query_words = normalize_inventory_words(query)
    if not query_words:
        raise ValueError("Incluye el nombre del producto, su presentación o el SKU.")

    exact_sku_match = [
        row for row in rows
        if normalize_inventory_words(row["sku"]) == query_words
    ]
    matches = exact_sku_match or [
        row for row in rows if query_words.issubset(row["words"])
    ]
    if not matches:
        distinctive_query_words = {
            word for word in query_words
            if not word.isdigit() and word not in NON_DISTINCTIVE_QUERY_WORDS
        }
        scored_matches = []
        for row in rows:
            exact_count = 0
            matched_count = 0
            distance_total = 0
            used_fuzzy_match = False
            for query_word in distinctive_query_words:
                if query_word in row["words"]:
                    matched_count += 1
                    exact_count += 1
                    continue
                closest_words = [
                    word_distance(query_word, inventory_word)
                    for inventory_word in row["words"]
                    if len(query_word) >= FUZZY_WORD_MIN_LENGTH
                    and abs(len(query_word) - len(inventory_word)) <= FUZZY_WORD_MAX_DISTANCE
                ]
                closest_distance = min(closest_words, default=FUZZY_WORD_MAX_DISTANCE + 1)
                if closest_distance <= FUZZY_WORD_MAX_DISTANCE:
                    matched_count += 1
                    distance_total += closest_distance
                    used_fuzzy_match = True
            if matched_count:
                scored_matches.append(
                    ((matched_count, exact_count, -distance_total), row, used_fuzzy_match)
                )
        best_score = max((score for score, _, _ in scored_matches), default=None)
        ranked_matches = [
            (row, used_fuzzy_match)
            for score, row, used_fuzzy_match in scored_matches
            if score == best_score
        ]
        if ranked_matches:
            closest_matches = any(used_fuzzy_match for _, used_fuzzy_match in ranked_matches)
            matches = [row for row, _ in ranked_matches]
        else:
            closest_matches = False
    else:
        closest_matches = False
    if not matches:
        return {"status": "not_found"}
    if len(matches) > 1:
        result = {
            "status": "closest_match" if closest_matches else "ambiguous",
            "candidates": [
                inventory_item(row, include_price)
                for row in matches[:10]
            ],
        }
        if include_price:
            result["priceRequested"] = True
        return result

    match = matches[0]
    del match["words"]
    del match["aliases"]
    item = inventory_item(match, include_price)
    result = {
        "status": "closest_match" if closest_matches else "found",
        "item": item,
    }
    if include_price:
        result["priceRequested"] = True
    if requested_fields:
        result["requestedFields"] = requested_fields
    return result
