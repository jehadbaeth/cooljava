# 017 · Command Pattern with Undo and Redo in Lambdas

> An undoable action is just two lambdas and a name. Two stacks turn them into Ctrl+Z, and one subtle capture bug turns them into data loss.

**Since:** Java 16 · **Category:** [Design Patterns, Modernized](../README.md#design-patterns-modernized) · **Level:** Intermediate · **Verdict:** ✅ Production

## The problem

The Gang of Four Command pattern turns a request into an object, so it can be queued, logged and, most famously, undone. The classic Java rendering is an interface with `execute()` and `undo()` plus one class per action: `InsertTextCommand`, `DeleteTextCommand`, `ReplaceTextCommand`, each with a constructor, fields and two methods. For a text editor that is a lot of ceremony around what are really two lines of code each.

## The trick

A command is **a name plus two `Runnable`s**, so make it a record and build instances with lambdas:

```java
record Command(String name, Runnable execute, Runnable undo) {}

Command insert(int at, String s) {
    return new Command("insert '" + s + "'",
            () -> text.insert(at, s),
            () -> text.delete(at, at + s.length()));
}
```

The history is two `Deque`s:

* **perform** runs the command, pushes it on the undo stack and **clears the redo stack** (a new edit makes the old future meaningless),
* **undo** pops from the undo stack, runs `undo`, and pushes onto the redo stack,
* **redo** does the opposite.

A **macro** is a command made of commands: run the parts in order, undo them in reverse order. The undo stack sees one entry, so one Ctrl+Z undoes the whole macro.

## Full example

```java run
import java.util.*;
import java.util.function.*;

public class UndoRedoDemo {

    /** A command is a name plus two actions. */
    record Command(String name, Runnable execute, Runnable undo) {
        /** Runs the parts in order and undoes them in reverse order. */
        static Command macro(String name, List<Command> parts) {
            List<Command> reversed = new ArrayList<>(parts);
            Collections.reverse(reversed);
            return new Command(name,
                    () -> parts.forEach(c -> c.execute().run()),
                    () -> reversed.forEach(c -> c.undo().run()));
        }
    }

    /** The receiver: a plain text buffer that knows nothing about undo. */
    static final class Buffer {
        private final StringBuilder text = new StringBuilder();
        @Override public String toString() { return "\"" + text + "\""; }

        Command insert(int at, String s) {
            return new Command("insert '" + s + "'",
                    () -> text.insert(at, s),
                    () -> text.delete(at, at + s.length()));
        }

        Command delete(int from, int to) {
            var removed = new StringBuilder();   // filled when the command runs, not when it is built
            return new Command("delete " + from + ".." + to,
                    () -> { removed.setLength(0); removed.append(text, from, to); text.delete(from, to); },
                    () -> text.insert(from, removed));
        }

        // The tempting version: it remembers the doomed text when the command is built.
        Command deleteEagerly(int from, int to) {
            String removed = text.substring(from, to);
            return new Command("delete " + from + ".." + to,
                    () -> text.delete(from, to),
                    () -> text.insert(from, removed));
        }
    }

    /** The invoker: two stacks. */
    static final class History {
        private final Deque<Command> undo = new ArrayDeque<>();
        private final Deque<Command> redo = new ArrayDeque<>();

        void perform(Command c) {
            c.execute().run();
            undo.push(c);
            redo.clear();               // a new edit invalidates the old future
        }

        boolean undo() { return move(undo, redo, Command::undo); }
        boolean redo() { return move(redo, undo, Command::execute); }

        private static boolean move(Deque<Command> from, Deque<Command> to, Function<Command, Runnable> action) {
            Command c = from.poll();
            if (c == null) return false;
            action.apply(c).run();
            to.push(c);
            return true;
        }

        List<String> undoNames() { return undo.stream().map(Command::name).toList(); }
    }

    /** The memento alternative: immutable snapshots instead of inverse operations. */
    static final class SnapshotEditor {
        private String text = "";
        private final Deque<String> undo = new ArrayDeque<>();
        private final Deque<String> redo = new ArrayDeque<>();

        void edit(UnaryOperator<String> change) { undo.push(text); text = change.apply(text); redo.clear(); }
        void undo() { if (!undo.isEmpty()) { redo.push(text); text = undo.pop(); } }
        void redo() { if (!redo.isEmpty()) { undo.push(text); text = redo.pop(); } }
        int storedChars() { return undo.stream().mapToInt(String::length).sum() + redo.stream().mapToInt(String::length).sum(); }
    }

    public static void main(String[] args) {
        var buf = new Buffer();
        var history = new History();
        history.perform(buf.insert(0, "hello"));
        history.perform(buf.insert(5, " world"));
        history.perform(Command.macro("shout", List.of(buf.delete(0, 5), buf.insert(0, "HELLO"), buf.insert(11, "!"))));
        System.out.println("edited:  " + buf + "  undo stack " + history.undoNames());
        history.undo();
        System.out.println("undo:    " + buf);
        history.undo();
        System.out.println("undo:    " + buf);
        history.redo();
        System.out.println("redo:    " + buf);
        history.perform(buf.insert(11, "?"));
        System.out.println("new:     " + buf);
        System.out.println("redo possible after a new edit? " + history.redo());

        // When is the deleted text captured? Both macros are built while the text is "hello world".
        var b = new Buffer();
        var h = new History();
        h.perform(b.insert(0, "hello world"));
        h.perform(Command.macro("quote and cut", List.of(b.insert(0, ">> "), b.delete(3, 9))));
        System.out.print("captured on execute: " + b);
        h.undo();
        System.out.println(" -> undo -> " + b);
        h.perform(Command.macro("quote and cut", List.of(b.insert(0, ">> "), b.deleteEagerly(3, 9))));
        System.out.print("captured on build:   " + b);
        h.undo();
        System.out.println(" -> undo -> " + b + "  <- corrupted");

        // Memento: no inverse needed, even for a lossy edit like toUpperCase.
        var editor = new SnapshotEditor();
        editor.edit(t -> t + "hello");
        editor.edit(t -> t + " world");
        editor.edit(t -> t.toUpperCase(Locale.ROOT) + "!");
        System.out.println("memento: \"" + editor.text + "\", snapshots hold " + editor.storedChars() + " chars");
        editor.undo();
        editor.undo();
        System.out.println("undo x2: \"" + editor.text + "\", snapshots hold " + editor.storedChars() + " chars");
        editor.redo();
        System.out.println("redo:    \"" + editor.text + "\"");
    }
}
```

Output:

```text output
edited:  "HELLO world!"  undo stack [shout, insert ' world', insert 'hello']
undo:    "hello world"
undo:    "hello"
redo:    "hello world"
new:     "hello world?"
redo possible after a new edit? false
captured on execute: ">> world" -> undo -> "hello world"
captured on build:   ">> world" -> undo -> "lo worworld"  <- corrupted
memento: "HELLO WORLD!", snapshots hold 16 chars
undo x2: "hello", snapshots hold 23 chars
redo:    "hello world"
```

## How it works

* **The receiver stays ignorant.** `Buffer` is a `StringBuilder` with factory methods that *return* commands instead of changing text directly. All undo logic lives in the lambdas and in `History`, so the same buffer could be driven without any undo at all.
* **Each lambda pair is an exact inverse.** `insert(at, s)` undoes itself with `delete(at, at + s.length())`. Inverses are cheap (they store a delta, not a copy of the document), but every new command needs a correct one, and that is where bugs live.
* **The macro reverses its parts on undo.** "shout" first deletes `hello`, then inserts `HELLO`, then appends `!`. Undoing in the same order would delete from the wrong positions; undoing in reverse puts every part back into exactly the state it saw. The undo stack shows a single entry named `shout`, so one undo restored `"hello world"` in one step.
* **The redo stack is cleared by a new edit.** After undo, undo, redo, the document is `"hello world"` with `"HELLO world!"` still waiting on the redo stack. Typing `?` throws that future away, and `redo()` reports `false`. Without the `clear()` you could "redo" the shout onto a text that no longer has the shape it expects.
* **`delete` captures its text on execute, not on build.** Both macros are built while the buffer reads `"hello world"`, but by the time the delete runs, the inserted `>> ` has shifted everything by three characters. The correct version reads the doomed text inside `execute`, so it removes and later restores `hello `. The eager version captured `lo wor` up front, and its undo inserts that instead: the output shows `"lo worworld"` where `"hello world"` should be. Nothing crashed, which is what makes this bug nasty.
* **The memento version never computes an inverse.** It pushes the whole previous text before each edit and restores it on undo, so even `toUpperCase`, which has no inverse at all, is undoable. The cost is visible in the `chars` numbers: three short edits already keep 16 characters of snapshots, and after two undos the redo side holds both full versions, 23 characters in total. Every snapshot is a full copy of the document.

## Gotchas

* **Commands that capture positions are fragile.** `delete(3, 9)` means "characters 3 to 9 at the time I run". As long as commands only run from the undo and redo stacks in strict order, the positions are right. Run them out of order (collaborative editing, reordering macros) and you need operational transforms or CRDTs, not this pattern.
* **Undo can fail too.** If an undo action throws, the history is half moved. Make `undo` and `execute` either total (cannot fail) or catch the failure and leave both stacks untouched.
* **Unbounded history is a memory leak with a nice UI.** Cap the undo stack (`if (undo.size() > LIMIT) undo.removeLast()`), especially with snapshots. Swing's `UndoManager` defaults to 100 edits for the same reason.
* **Coalesce tiny edits.** Nobody wants one undo step per keystroke. Merge consecutive inserts into one command before pushing it, or group them with a macro.
* **Do not mix the two styles in one history.** A snapshot restore and an inverse delta on the same buffer will disagree about what "previous" means.

## When to use it (and when not to)

Use command records whenever actions must be undoable, replayable or logged: editors, drawing tools, admin consoles, configuration wizards, game moves. Prefer **mementos** when the state is small or immutable already (a record, a persistent collection, a game board), because restoring a snapshot is trivially correct. Prefer **commands** when the state is large and edits are small, and you are willing to test every inverse.

For Swing applications, the JDK already ships the pattern in `javax.swing.undo`: `UndoableEdit` is the command, `CompoundEdit` is the macro and `UndoManager` is the history. For a database, a transaction is the undo you want; do not reimplement rollback by hand.

## Related

* [014 · Withers: Painless Copies of Immutable Records](014-record-withers.md), cheap snapshots for the memento style
* [018 · Middleware Chains: Chain of Responsibility as Function Composition](018-middleware-chain.md), another pattern reduced to lambdas
* [025 · Event Sourcing in 60 Lines](../03-build-it-yourself/025-event-sourcing.md), where the command log becomes the source of truth
* [016 · State Machines with Enums and Sealed Types](016-state-machines.md)

## Sources

* Erich Gamma, Richard Helm, Ralph Johnson and John Vlissides, *Design Patterns* (1994), chapters on Command and Memento
* [Command pattern](https://en.wikipedia.org/wiki/Command_pattern) and [Memento pattern](https://en.wikipedia.org/wiki/Memento_pattern), Wikipedia
* [`javax.swing.undo.UndoManager` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.desktop/javax/swing/undo/UndoManager.html)
* [`java.util.ArrayDeque` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ArrayDeque.html)
