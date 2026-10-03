# 027 · A JSON Parser with Sealed Types

> JSON is six shapes and a handful of rules, which makes it the perfect first parser to write by hand. Sealed records give you the tree, recursive descent gives you the code, and a pattern matching `switch` prints it back.

**Since:** Java 21 · **Category:** [Build It Yourself](../README.md#build-it-yourself) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

The JDK ships no JSON parser. The moment a small tool needs one (a CLI that reads a config file, a build step, a test that checks a response body), the reflex is to add Jackson. That is usually the right call, and this document ends by saying so. But a parser is also one of the best exercises in programming: the grammar fits on a business card, the data model is a textbook algebraic data type, and the failure modes (bad escapes, huge numbers, hostile nesting) are real.

Most hand-rolled parsers go wrong in three places: they return `Object` and `Map<String, Object>` soup that nobody can `switch` over safely, they report errors as "invalid JSON" without saying where, and they silently accept things the spec forbids.

## The trick

**Model the value as a sealed interface with one record per JSON type.** JSON has exactly six shapes (object, array, string, number, boolean, null), so the compiler can check that every `switch` handles all six:

```java
sealed interface JsonValue {}
record JsonObject(Map<String, JsonValue> members) implements JsonValue {}
record JsonArray(List<JsonValue> items) implements JsonValue {}
record JsonString(String value) implements JsonValue {}
record JsonNumber(BigDecimal value) implements JsonValue {}
record JsonBool(boolean value) implements JsonValue {}
record JsonNull() implements JsonValue {}
```

**Then write one method per grammar rule.** This is *recursive descent*: the parser is a cursor into the text, `value()` looks at one character to decide which rule applies, and `object()` and `array()` call `value()` again for their children. The recursion in the code mirrors the recursion in the data. Nothing needs a tokenizer, because every JSON token starts with a character that identifies it (`{`, `[`, `"`, `t`, `f`, `n`, `-` or a digit).

Three decisions turn the toy into something you can trust:

* **Numbers are `BigDecimal`.** A `double` cannot hold `12345678901234567890.123456789`, and JSON does not promise that numbers fit any particular machine type.
* **Every error carries a position.** One helper turns an offset into `line L, column C`, and every `throw` goes through it.
* **Printing escapes everything outside printable ASCII**, so `parse(print(x)).equals(x)` holds and the output survives any terminal.

## Full example

The library part (records, parser and printer) is 154 lines without blank lines and comments. That is more than a bare-bones parser needs, because it also rejects what the spec forbids (leading zeros, raw control characters, duplicate keys, absurd nesting). The rest is the demo.

```java run
import java.math.BigDecimal;
import java.util.*;
import java.util.stream.Collectors;

public class JsonDemo {

    // ---------- The data model: exactly six shapes ----------

    sealed interface JsonValue {}
    record JsonObject(Map<String, JsonValue> members) implements JsonValue {
        JsonObject { members = Collections.unmodifiableMap(new LinkedHashMap<>(members)); }   // keeps insertion order
    }
    record JsonArray(List<JsonValue> items) implements JsonValue {
        JsonArray { items = List.copyOf(items); }
    }
    record JsonString(String value) implements JsonValue {}
    record JsonNumber(BigDecimal value) implements JsonValue {}
    record JsonBool(boolean value) implements JsonValue {}
    record JsonNull() implements JsonValue {}

    // ---------- The parser: one method per grammar rule ----------

    static final class JsonParseException extends RuntimeException {
        JsonParseException(String message) { super(message); }
    }

    static JsonValue parse(String text) { return new Parser(text).document(); }

    static final class Parser {
        private static final int MAX_DEPTH = 64;
        private final String text;
        private int pos;

        Parser(String text) { this.text = text; }

        JsonValue document() {
            JsonValue value = value(0);
            skipWhitespace();
            if (pos < text.length()) throw error("unexpected trailing characters", pos);
            return value;
        }

        JsonValue value(int depth) {
            skipWhitespace();
            int c = peek();
            return switch (c) {
                case -1 -> throw error("unexpected end of input", pos);
                case '{' -> object(depth + 1);
                case '[' -> array(depth + 1);
                case '"' -> new JsonString(string());
                case 't' -> literal("true", new JsonBool(true));
                case 'f' -> literal("false", new JsonBool(false));
                case 'n' -> literal("null", new JsonNull());
                default -> {
                    if (c == '-' || (c >= '0' && c <= '9')) yield number();
                    throw error("unexpected character '" + (char) c + "'", pos);
                }
            };
        }

        JsonValue object(int depth) {
            enter(depth);
            var members = new LinkedHashMap<String, JsonValue>();
            if (!consumeIf('}')) {
                do {
                    skipWhitespace();
                    int keyPos = pos;
                    if (peek() != '"') throw error("expected a string key", pos);
                    String key = string();
                    expect(':', "':' after key");
                    if (members.put(key, value(depth)) != null) throw error("duplicate key \"" + key + "\"", keyPos);
                } while (consumeIf(','));
                expect('}', "',' or '}'");
            }
            return new JsonObject(members);
        }

        JsonValue array(int depth) {
            enter(depth);
            var items = new ArrayList<JsonValue>();
            if (!consumeIf(']')) {
                do items.add(value(depth)); while (consumeIf(','));
                expect(']', "',' or ']'");
            }
            return new JsonArray(items);
        }

        String string() {
            int start = pos++;                                  // skip the opening quote
            var sb = new StringBuilder();
            while (peek() != '"') {
                int c = peek();
                if (c == -1) throw error("unterminated string", start);
                if (c < 0x20) throw error("raw control character in string", pos);
                pos++;
                if (c != '\\') { sb.append((char) c); continue; }
                int escape = peek();
                int simple = "\"\\/bfnrt".indexOf(escape);
                if (simple >= 0) sb.append("\"\\/\b\f\n\r\t".charAt(simple));
                else if (escape == 'u') {                       // one UTF-16 code unit, so surrogate pairs just work
                    int code = 0;
                    for (int i = 0; i < 4; i++) {
                        pos++;
                        int digit = hex(peek());
                        if (digit < 0) throw error("invalid \\u escape, expected 4 hex digits", pos);
                        code = code * 16 + digit;
                    }
                    sb.append((char) code);
                } else throw error("invalid escape", pos - 1);
                pos++;
            }
            pos++;                                              // skip the closing quote
            return sb.toString();
        }

        JsonValue number() {                                    // -? (0 | [1-9][0-9]*) (. [0-9]+)? ([eE] [+-]? [0-9]+)?
            int start = pos;
            if (peek() == '-') pos++;
            if (peek() == '0') pos++;
            else if (!digits()) throw error("expected a digit", pos);
            if (peek() == '.') { pos++; if (!digits()) throw error("expected a digit after '.'", pos); }
            if (peek() == 'e' || peek() == 'E') {
                pos++;
                if (peek() == '+' || peek() == '-') pos++;
                if (!digits()) throw error("expected a digit in the exponent", pos);
            }
            return new JsonNumber(new BigDecimal(text.substring(start, pos)));
        }

        // ---- helpers ----
        int peek() { return pos < text.length() ? text.charAt(pos) : -1; }
        static int hex(int c) { return Character.digit(c < 128 ? c : -1, 16); }   // ASCII only: digit() also accepts fullwidth digits
        boolean digits() { int start = pos; while (peek() >= '0' && peek() <= '9') pos++; return pos > start; }
        void skipWhitespace() { while (peek() == ' ' || peek() == '\t' || peek() == '\n' || peek() == '\r') pos++; }
        boolean consumeIf(char c) { skipWhitespace(); if (peek() != c) return false; pos++; return true; }
        void expect(char c, String what) { if (!consumeIf(c)) throw error("expected " + what, pos); }
        void enter(int depth) { if (depth > MAX_DEPTH) throw error("nesting deeper than " + MAX_DEPTH, pos); pos++; }
        JsonValue literal(String word, JsonValue result) {
            if (!text.startsWith(word, pos)) throw error("expected '" + word + "'", pos);
            pos += word.length();
            return result;
        }
        JsonParseException error(String message, int at) {
            int line = 1, column = 1;
            for (int i = 0; i < at; i++) { if (text.charAt(i) == '\n') { line++; column = 1; } else column++; }
            return new JsonParseException(message + " at line " + line + ", column " + column);
        }
    }

    // ---------- The printer: one exhaustive switch, no default branch ----------

    static String print(JsonValue value, int level) {
        String newline = "\n" + "  ".repeat(level + 1);
        String closing = "\n" + "  ".repeat(level);
        return switch (value) {
            case JsonNull() -> "null";
            case JsonBool(boolean b) -> String.valueOf(b);
            case JsonNumber(BigDecimal n) -> n.toString();
            case JsonString(String s) -> quote(s);
            case JsonArray(List<JsonValue> items) -> items.isEmpty() ? "[]" : items.stream()
                    .map(item -> newline + print(item, level + 1))
                    .collect(Collectors.joining(",", "[", closing + "]"));
            case JsonObject(Map<String, JsonValue> members) -> members.isEmpty() ? "{}" : members.entrySet().stream()
                    .map(e -> newline + quote(e.getKey()) + ": " + print(e.getValue(), level + 1))
                    .collect(Collectors.joining(",", "{", closing + "}"));
        };
    }

    static String quote(String s) {
        var sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"') sb.append("\\\"");
            else if (c == '\\') sb.append("\\\\");
            else if (c == '\n') sb.append("\\n");
            else if (c == '\t') sb.append("\\t");
            else if (c < 0x20 || c > 0x7e) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.append('"').toString();
    }

    // ---------- Demo ----------

    public static void main(String[] args) {
        // Backslashes are doubled because this is a Java text block holding JSON text.
        String source = """
                {
                  "name": "Ada Lovelace",
                  "born": 1815,
                  "tags": ["math", "poetry", "engines"],
                  "address": {"city": "London", "geo": [51.5074, -0.1278]},
                  "retired": false,
                  "spouse": null,
                  "note": "tab\\there, \\"quoted\\", smile \\uD83D\\uDE00, caf\\u00e9"
                }
                """;
        JsonValue doc = parse(source);
        String pretty = print(doc, 0);
        System.out.println(pretty);

        // Nested record patterns walk the tree without a single cast.
        if (doc instanceof JsonObject(var members)
                && members.get("address") instanceof JsonObject(var address)
                && address.get("city") instanceof JsonString(var city)) {
            System.out.println("city = " + city);
        }

        System.out.println("round trip ok: " + parse(pretty).equals(doc));

        for (String number : List.of("1.0", "1.00", "1e3", "-0", "12345678901234567890.123456789")) {
            System.out.println(number + " prints as " + print(parse(number), 0));
        }
        System.out.println("1.0 equals 1.00? " + parse("1.0").equals(parse("1.00")));

        System.out.println("--- errors");
        String[] bad = {
            "[1, 2,]", "{\"a\": 1,}", "{\"a\": 1, \"a\": 2}", "[01]", "[1 2]", "[1.]", "tru", "[1, 2] x",
            "\"abc", "\"bad \\u12G4\"", "\"bad \\x\"", "\"tab\there\"",
            "{\n  \"a\": [1,\n  2 3]\n}", "[".repeat(100)
        };
        for (String input : bad) {
            String shown = input.length() > 40 ? input.substring(0, 10) + "... (" + input.length() + " chars)" : input;
            try {
                parse(input);
                System.out.println("accepted?! " + shown);
            } catch (JsonParseException e) {
                System.out.printf("%-26s %s%n", shown.replace("\n", "\\n").replace("\t", "\\t"), e.getMessage());
            }
        }
    }
}
```

Output:

```text output
{
  "name": "Ada Lovelace",
  "born": 1815,
  "tags": [
    "math",
    "poetry",
    "engines"
  ],
  "address": {
    "city": "London",
    "geo": [
      51.5074,
      -0.1278
    ]
  },
  "retired": false,
  "spouse": null,
  "note": "tab\there, \"quoted\", smile \ud83d\ude00, caf\u00e9"
}
city = London
round trip ok: true
1.0 prints as 1.0
1.00 prints as 1.00
1e3 prints as 1E+3
-0 prints as 0
12345678901234567890.123456789 prints as 12345678901234567890.123456789
1.0 equals 1.00? false
--- errors
[1, 2,]                    unexpected character ']' at line 1, column 7
{"a": 1,}                  expected a string key at line 1, column 9
{"a": 1, "a": 2}           duplicate key "a" at line 1, column 10
[01]                       expected ',' or ']' at line 1, column 3
[1 2]                      expected ',' or ']' at line 1, column 4
[1.]                       expected a digit after '.' at line 1, column 4
tru                        expected 'true' at line 1, column 1
[1, 2] x                   unexpected trailing characters at line 1, column 8
"abc                       unterminated string at line 1, column 1
"bad \u12G4"               invalid \u escape, expected 4 hex digits at line 1, column 10
"bad \x"                   invalid escape at line 1, column 6
"tab\there"                raw control character in string at line 1, column 5
{\n  "a": [1,\n  2 3]\n}   expected ',' or ']' at line 3, column 5
[[[[[[[[[[... (100 chars)  nesting deeper than 64 at line 1, column 65
```

## How it works

* **One character of lookahead picks the rule.** `value()` peeks and dispatches: `{` object, `[` array, `"` string, `t`, `f`, `n` keywords, anything else must start a number. That makes the grammar LL(1), which is why there is no tokenizer and no backtracking.
* **The recursion in the code is the recursion in the data.** `object()` and `array()` call `value()` for their children, so nesting depth in the text becomes call stack depth in the JVM. Elegant, and the reason for `MAX_DEPTH`.
* **Records are shallowly immutable, so the constructors copy.** A `LinkedHashMap` keeps the key order for the printer, while record `equals` goes through `Map.equals`, which ignores order. JSON objects are unordered, so `{"a":1,"b":2}` equals `{"b":2,"a":1}`.
* **`\u` escapes need no pairing logic.** Four hex digits become one `char`, a UTF-16 code unit, so `\uD83D\uDE00` becomes the two surrogates that form U+1F600, as the spec intends. The printer escapes every `char` above `~` again (`\ud83d\ude00` and `caf\u00e9` in the output), which keeps the output pure ASCII and the round trip exact.
* **Numbers keep their scale.** `new BigDecimal("1.0")` remembers its scale, so `1.00` prints as `1.00` and is not `equals` to `1.0` (use `compareTo` for numeric equality). `1e3` comes back as `1E+3`, valid JSON but surprising, and `-0` becomes `0` because `BigDecimal` has no negative zero. The round trip still holds, because `toString` yields text that parses back to the same value and scale.
* **Errors point at the culprit.** Every `throw` goes through `error(message, offset)`, which counts newlines to get a line and column, and only runs on failure. The trailing comma in `[1, 2,]` is blamed on the `]` (column 7), the unterminated string on its opening quote, the duplicate key on the second `"a"`, and `[01]` on the `1`: the parser read `0` as a complete number and then wanted a comma. The tab in the `"tab\there"` row is a real tab that the demo prints as `\t`.
* **The printer is one expression.** The `switch (value)` has six cases and no `default`, because `JsonValue` is sealed. Record patterns pull out the components in the case label, so there are no casts and no getters.

The exhaustiveness is worth seeing fail. Add a seventh shape to the hierarchy and forget to update the printer, and javac refuses to compile:

```java compile-fail
public class MissingCase {
    sealed interface JsonValue {}
    record JsonString(String value) implements JsonValue {}
    record JsonNull() implements JsonValue {}
    record JsonBool(boolean value) implements JsonValue {}      // the new shape

    static String print(JsonValue value) {
        return switch (value) {
            case JsonString(String s) -> "\"" + s + "\"";
            case JsonNull() -> "null";
        };
    }
}
```

```text compile-error
MissingCase.java:8: error: the switch expression does not cover all possible input values
        return switch (value) {
               ^
1 error
```

## Gotchas

* **Without a depth limit, hostile input is a denial of service.** 100,000 opening brackets with `MAX_DEPTH` removed throw `StackOverflowError`, an `Error` that callers do not expect from a parser. Jackson has the same protection built in since 2.15 as `StreamReadConstraints`, with limits on nesting depth, number length and string length.
* **`BigDecimal` moves the problem.** `1e999999999` parses instantly, because only the exponent is stored, and `toPlainString()` or `toBigInteger()` would then try to build a billion digits. Cap the lexeme length or never expand untrusted numbers.
* **`Character` methods are not ASCII.** `Character.digit('\uFF11', 16)` returns 1 for a fullwidth digit one, and `Character.isWhitespace` accepts more than JSON's four whitespace characters. The parser compares explicitly, and `hex` guards `Character.digit` with an ASCII check.
* **Duplicate keys are a policy decision.** RFC 8259 only says names *should* be unique and that behavior is otherwise unpredictable. Most parsers silently keep the last value, so one document can mean different things to two systems. The toy rejects duplicates, and Jackson can (`JsonParser.Feature.STRICT_DUPLICATE_DETECTION`) but does not by default.
* **Lone surrogates pass.** `"\ud800"` is valid by the grammar, so the toy accepts it and yields a string that cannot be encoded as well-formed UTF-8. Columns also count UTF-16 code units, and a tab counts as one.
* **A `Parser` is a single-use cursor.** Make one per call, as `parse` does. It is not thread-safe.

## When to use it (and when not to)

Write your own when you need a few dozen lines of JSON handling and no dependency: a single-file script run with `java Tool.java` (which cannot pull in libraries, see [045](../05-modern-language/045-java-scripting.md)), a build helper, a test fixture reader, or a lesson. The sealed tree is pleasant to work with and the error messages are better than many production parsers give.

Do not use it for untrusted input at volume, large documents or data binding. Use [Jackson](https://github.com/FasterXML/jackson) (`jackson-databind`, or the streaming `JsonParser` for big inputs); Gson and Jakarta JSON Processing are fine too. The toy leaves out streaming (it needs the whole text as a `String`), binding to records and POJOs (the bulk of what Jackson does), JSON5 and JSONC dialects (comments, trailing commas), limits on number and string length, charset and BOM handling for raw bytes, and every performance trick a real parser plays. Nicolas Seriot's test suite (see Sources) found disagreements between nearly all well-known parsers on edge cases: "parsing JSON" is not one solved problem.

## Related

* [028 · Parser Combinators: Grammars as Code](028-parser-combinators.md), the same job with grammars as values instead of methods
* [026 · Property-Based Testing in 80 Lines](026-property-based-testing.md), where `parse(print(x)).equals(x)` is the textbook property to throw at this parser
* [040 · Algebraic Data Types with Sealed Interfaces and Records](../05-modern-language/040-algebraic-data-types.md)
* [041 · Pattern Matching for switch: The Complete Toolkit](../05-modern-language/041-switch-pattern-matching.md)

## Sources

* [RFC 8259: The JavaScript Object Notation (JSON) Data Interchange Format](https://www.rfc-editor.org/rfc/rfc8259)
* [Introducing JSON](https://www.json.org/), the grammar as railroad diagrams
* Nicolas Seriot, [Parsing JSON is a Minefield](https://seriot.ch/parsing_json.php) and its [test suite](https://github.com/nst/JSONTestSuite)
* [JEP 409: Sealed Classes](https://openjdk.org/jeps/409), [JEP 440: Record Patterns](https://openjdk.org/jeps/440) and [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441)
* Jackson, [`StreamReadConstraints`](https://javadoc.io/doc/com.fasterxml.jackson.core/jackson-core/latest/com/fasterxml/jackson/core/StreamReadConstraints.html) and the [Jackson project](https://github.com/FasterXML/jackson)
