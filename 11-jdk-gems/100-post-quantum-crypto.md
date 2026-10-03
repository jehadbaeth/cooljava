# 100 · Post-Quantum Cryptography in Plain Java

> A large enough quantum computer breaks RSA and elliptic curves, and someone may already be recording your traffic to read it later. Since JDK 24 the JDK ships the two NIST-standardized replacements, ML-KEM and ML-DSA, behind the `KeyPairGenerator`, `KEM` and `Signature` APIs you already know.

**Since:** Java 25 · **Category:** [JDK Gems](../README.md#jdk-gems) · **Level:** Intermediate · **Verdict:** ⚠️ Situational

## The problem

Every public-key algorithm in common use today (RSA, Diffie-Hellman, ECDH, ECDSA, EdDSA) rests on the difficulty of factoring or of discrete logarithms. Shor's algorithm solves both in polynomial time on a quantum computer of sufficient size. Nobody can say when such a machine will exist, but the threat model does not wait for it: an adversary can record encrypted traffic today and decrypt it later ("harvest now, decrypt later"). Anything that must stay secret for fifteen years is already exposed to that bet. Signatures are less urgent, since a forgery has to be produced while it still matters, apart from long-lived trust anchors such as code signing.

The symmetric half of the toolbox is in better shape. Grover's algorithm only gives a quadratic speedup against AES and SHA-2, so 256-bit keys remain comfortable. What needs replacing is key exchange and signatures. In August 2024 NIST published the first standards for that: FIPS 203 (ML-KEM, derived from CRYSTALS-Kyber) for key encapsulation and FIPS 204 (ML-DSA, derived from CRYSTALS-Dilithium) for signatures. Until JDK 24, using them from Java meant a third-party provider.

## The trick

Post-quantum key exchange is a four-part assembly, and every part is a JDK class:

| Part | Job | JDK class | Arrived |
|---|---|---|---|
| KEM | Agree on a shared secret | `javax.crypto.KEM`, algorithm `ML-KEM` | KEM API in 21 ([JEP 452](https://openjdk.org/jeps/452)), ML-KEM in 24 (JEP 496) |
| KDF | Turn that secret into keys | `javax.crypto.KDF`, algorithm `HKDF-SHA256` | Preview in 24 (JEP 478), final in 25 (JEP 510) |
| AEAD | Encrypt and authenticate data | `Cipher`, `AES/GCM/NoPadding` | Always there |
| Signature | Authenticate the other side | `java.security.Signature`, algorithm `ML-DSA` | 24 (JEP 497) |

A KEM is not Diffie-Hellman. In Diffie-Hellman both sides contribute and compute the same value. In a KEM, one side holds a key pair, and the other side takes the public key, **encapsulates**: the call produces a fresh random secret together with a ciphertext that wraps it. Only the holder of the private key can **decapsulate** the ciphertext and recover the same secret.

```java
KEM kem = KEM.getInstance("ML-KEM");
KEM.Encapsulated fromBob = kem.newEncapsulator(alice.getPublic()).encapsulate();      // Bob: secret and ciphertext
SecretKey aliceSecret = kem.newDecapsulator(alice.getPrivate())
        .decapsulate(fromBob.encapsulation());                                        // Alice: the same secret
```

The example below runs the whole chain in one JVM: Alice generates an ML-KEM key pair, Bob encapsulates, both derive an AES key with HKDF, Bob encrypts a message with AES-GCM, Alice decrypts it, and Bob signs the handshake with ML-DSA. The ML-KEM and ML-DSA algorithms need JDK 24, and the final KDF API needs JDK 25, hence the badge. The program prints only sizes and booleans, never key material.

## Full example

```java run
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.Signature;
import java.security.spec.AlgorithmParameterSpec;
import java.security.spec.NamedParameterSpec;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.KDF;
import javax.crypto.KEM;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.HKDFParameterSpec;

public class PostQuantum {

    static KeyPair generate(String algorithm, NamedParameterSpec parameters) throws GeneralSecurityException {
        KeyPairGenerator generator = KeyPairGenerator.getInstance(algorithm);
        generator.initialize(parameters);
        return generator.generateKeyPair();
    }

    static boolean same(SecretKey a, SecretKey b) {
        return MessageDigest.isEqual(a.getEncoded(), b.getEncoded());
    }

    // HKDF-SHA256: extract from the shared secret with a salt, expand to 32 bytes bound to a context label.
    static SecretKey deriveAesKey(SecretKey sharedSecret, byte[] salt, String context) throws GeneralSecurityException {
        AlgorithmParameterSpec spec = HKDFParameterSpec.ofExtract()
                .addIKM(sharedSecret)
                .addSalt(salt)
                .thenExpand(context.getBytes(StandardCharsets.UTF_8), 32);
        return KDF.getInstance("HKDF-SHA256").deriveKey("AES", spec);
    }

    static byte[] seal(SecretKey key, byte[] iv, byte[] header, String plaintext) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(128, iv));
        cipher.updateAAD(header);
        return cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
    }

    static String open(SecretKey key, byte[] iv, byte[] header, byte[] sealed) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, iv));
        cipher.updateAAD(header);
        return new String(cipher.doFinal(sealed), StandardCharsets.UTF_8);
    }

    public static void main(String[] args) throws Exception {
        System.out.println("-- 1. ML-KEM: Bob encapsulates a secret to Alice's public key");
        KeyPair alice = generate("ML-KEM", NamedParameterSpec.ML_KEM_768);
        KEM kem = KEM.getInstance("ML-KEM");
        KEM.Encapsulated fromBob = kem.newEncapsulator(alice.getPublic()).encapsulate();
        SecretKey aliceSecret = kem.newDecapsulator(alice.getPrivate()).decapsulate(fromBob.encapsulation());
        System.out.println("key algorithm        = " + alice.getPublic().getAlgorithm()
                + ", parameter set = " + ((NamedParameterSpec) alice.getPublic().getParams()).getName());
        System.out.println("public key           = " + alice.getPublic().getEncoded().length + " bytes");
        System.out.println("ciphertext           = " + fromBob.encapsulation().length + " bytes");
        System.out.println("shared secret        = " + fromBob.key().getEncoded().length + " bytes");
        System.out.println("both sides agree     = " + same(fromBob.key(), aliceSecret));

        KeyPair mallory = generate("ML-KEM", NamedParameterSpec.ML_KEM_768);
        SecretKey wrongKey = kem.newDecapsulator(mallory.getPrivate()).decapsulate(fromBob.encapsulation());
        byte[] damaged = fromBob.encapsulation().clone();
        damaged[0] ^= 1;
        SecretKey damagedSecret = kem.newDecapsulator(alice.getPrivate()).decapsulate(damaged);
        System.out.println("wrong private key    : no exception, secrets agree = " + same(fromBob.key(), wrongKey));
        System.out.println("damaged ciphertext   : no exception, secrets agree = " + same(fromBob.key(), damagedSecret));

        System.out.println("-- 2. HKDF-SHA256 turns the shared secret into an AES key");
        byte[] salt = new byte[16];
        new SecureRandom().nextBytes(salt);
        SecretKey bobKey = deriveAesKey(fromBob.key(), salt, "demo v1 bob to alice");
        SecretKey aliceKey = deriveAesKey(aliceSecret, salt, "demo v1 bob to alice");
        SecretKey otherContext = deriveAesKey(aliceSecret, salt, "demo v1 alice to bob");
        System.out.println("derived key          = " + bobKey.getAlgorithm() + ", " + bobKey.getEncoded().length * 8 + " bits");
        System.out.println("same inputs          = " + same(bobKey, aliceKey));
        System.out.println("other context label  = " + same(bobKey, otherContext));

        System.out.println("-- 3. AES-GCM with the derived key");
        byte[] iv = new byte[12];
        new SecureRandom().nextBytes(iv);
        byte[] header = "from=bob;to=alice".getBytes(StandardCharsets.UTF_8);
        String message = "meet at the usual quantum-safe place";
        byte[] sealed = seal(bobKey, iv, header, message);
        System.out.println("plaintext            = " + message.length() + " bytes, sealed = " + sealed.length + " bytes");
        System.out.println("alice decrypts       = " + open(aliceKey, iv, header, sealed));
        sealed[3] ^= 1;
        try {
            open(aliceKey, iv, header, sealed);
        } catch (GeneralSecurityException e) {
            System.out.println("tampered ciphertext  = " + e.getClass().getSimpleName());
        }

        System.out.println("-- 4. ML-DSA: Bob signs the handshake, Alice verifies");
        KeyPair bobSigning = generate("ML-DSA", NamedParameterSpec.ML_DSA_65);
        byte[] transcript = fromBob.encapsulation();
        Signature signer = Signature.getInstance("ML-DSA");
        signer.initSign(bobSigning.getPrivate());
        signer.update(transcript);
        byte[] signature = signer.sign();
        Signature verifier = Signature.getInstance("ML-DSA");
        verifier.initVerify(bobSigning.getPublic());
        verifier.update(transcript);
        System.out.println("key algorithm        = " + bobSigning.getPublic().getAlgorithm()
                + ", parameter set = " + ((NamedParameterSpec) bobSigning.getPublic().getParams()).getName());
        System.out.println("signature            = " + signature.length + " bytes");
        System.out.println("verified             = " + verifier.verify(signature));
        verifier.initVerify(bobSigning.getPublic());
        verifier.update(damaged);
        System.out.println("verified, damaged    = " + verifier.verify(signature));

        System.out.println("-- 5. what it costs on the wire (X.509 encoded public keys, in bytes)");
        for (String classical : List.of("X25519", "Ed25519")) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance(classical);
            System.out.printf("%-12s public key %5d%n", classical, generator.generateKeyPair().getPublic().getEncoded().length);
        }
        for (NamedParameterSpec spec : List.of(NamedParameterSpec.ML_KEM_512, NamedParameterSpec.ML_KEM_768, NamedParameterSpec.ML_KEM_1024)) {
            KeyPair pair = generate("ML-KEM", spec);
            KEM.Encapsulator encapsulator = kem.newEncapsulator(pair.getPublic());
            System.out.printf("%-12s public key %5d  ciphertext %5d  secret %d%n", spec.getName(),
                    pair.getPublic().getEncoded().length, encapsulator.encapsulationSize(), encapsulator.secretSize());
        }
        for (NamedParameterSpec spec : List.of(NamedParameterSpec.ML_DSA_44, NamedParameterSpec.ML_DSA_65, NamedParameterSpec.ML_DSA_87)) {
            KeyPair pair = generate("ML-DSA", spec);
            Signature s = Signature.getInstance("ML-DSA");
            s.initSign(pair.getPrivate());
            s.update(transcript);
            System.out.printf("%-12s public key %5d  signature  %5d%n", spec.getName(), pair.getPublic().getEncoded().length, s.sign().length);
        }
        Signature ed = Signature.getInstance("Ed25519");
        ed.initSign(KeyPairGenerator.getInstance("Ed25519").generateKeyPair().getPrivate());
        ed.update(transcript);
        System.out.printf("%-12s signature  %5d%n", "Ed25519", ed.sign().length);
    }
}
```

Output:

```text output
-- 1. ML-KEM: Bob encapsulates a secret to Alice's public key
key algorithm        = ML-KEM, parameter set = ML-KEM-768
public key           = 1206 bytes
ciphertext           = 1088 bytes
shared secret        = 32 bytes
both sides agree     = true
wrong private key    : no exception, secrets agree = false
damaged ciphertext   : no exception, secrets agree = false
-- 2. HKDF-SHA256 turns the shared secret into an AES key
derived key          = AES, 256 bits
same inputs          = true
other context label  = false
-- 3. AES-GCM with the derived key
plaintext            = 36 bytes, sealed = 52 bytes
alice decrypts       = meet at the usual quantum-safe place
tampered ciphertext  = AEADBadTagException
-- 4. ML-DSA: Bob signs the handshake, Alice verifies
key algorithm        = ML-DSA, parameter set = ML-DSA-65
signature            = 3309 bytes
verified             = true
verified, damaged    = false
-- 5. what it costs on the wire (X.509 encoded public keys, in bytes)
X25519       public key    44
Ed25519      public key    44
ML-KEM-512   public key   822  ciphertext   768  secret 32
ML-KEM-768   public key  1206  ciphertext  1088  secret 32
ML-KEM-1024  public key  1590  ciphertext  1568  secret 32
ML-DSA-44    public key  1334  signature   2420
ML-DSA-65    public key  1974  signature   3309
ML-DSA-87    public key  2614  signature   4627
Ed25519      signature     64
```

## How it works

### Section 1: ML-KEM

`KeyPairGenerator.getInstance("ML-KEM")` without any initialization gives ML-KEM-768. The example asks for it explicitly with `NamedParameterSpec.ML_KEM_768`, and `ML_KEM_512` and `ML_KEM_1024` are the other two standardized parameter sets, roughly NIST security categories 1, 3 and 5. A key reports the family name from `getAlgorithm()` and the parameter set through `getParams()` (the key interfaces gained `AsymmetricKey.getParams()` in JDK 22). `ML-KEM-768` also works directly as an algorithm name in `KeyPairGenerator` and `KEM`. The provider is `SunJCE`.

`encapsulate()` returns an `Encapsulated` object with the secret (`key()`) and the ciphertext (`encapsulation()`) that Bob sends to Alice. `secretSize()` and `encapsulationSize()` on the encapsulator tell you the sizes in advance. The secret is 32 bytes for every parameter set, and its `SecretKey` has the algorithm name `Generic`: it is raw input material, not an AES key, which is why section 2 exists.

The two lines after `both sides agree` show **implicit rejection**, a design decision of FIPS 203. Decapsulating with the wrong private key, or with a ciphertext that has one flipped bit, does not throw. It returns a pseudo-random secret that does not match. An attacker who submits forged ciphertexts therefore gets no error message to learn from, and the failure shows up one layer higher, when the AES-GCM tag does not verify.

### Section 2: HKDF

`KDF.getInstance("HKDF-SHA256")` is HKDF from RFC 5869, with `HKDF-SHA384` and `HKDF-SHA512` as siblings. The parameter spec builder reads like the RFC: `ofExtract().addIKM(secret).addSalt(salt).thenExpand(info, length)`. Extract condenses the input keying material and the salt into a pseudo-random key, and expand stretches it into as many bytes as you ask for, labeled with `info`. `deriveKey("AES", spec)` returns the result as a `SecretKey` of that algorithm, while `deriveData(spec)` gives the raw bytes.

The output shows the two properties that matter. Both sides derive the same key from the same inputs (`same inputs = true`), and a different context label gives an unrelated key (`other context label = false`). Give each direction of a conversation its own label and one shared secret yields two independent keys. The KEM secret is already uniformly random, so HKDF is not there to fix its quality. It is there for domain separation, and so that the same protocol shape works for any KEM.

### Section 3: AES-GCM

`AES/GCM/NoPadding` with a 128-bit tag adds 16 bytes: 36 bytes of plaintext become 52 bytes sealed. The `header` goes in as additional authenticated data: it is not encrypted, but any change to it makes decryption fail. Flipping one bit of the ciphertext fails the same way, with an `AEADBadTagException`. The IV is 12 random bytes, which is safe here because every handshake derives a fresh key and encrypts one message. Reusing an IV under one key breaks GCM completely.

### Section 4: ML-DSA

`Signature.getInstance("ML-DSA")` accepts a key of any parameter set, and `ML-DSA-44`, `ML-DSA-65` and `ML-DSA-87` also work as names. The default for the key pair generator is ML-DSA-65, and the provider is `SUN`. Signing and verifying follow the pattern from RSA and ECDSA, and a damaged message verifies as `false`. `verify` returns a boolean for a wrong signature, so check it.

### Section 5: the price

The numbers are the real argument against switching everything today. The 44 bytes of an X25519 or Ed25519 public key become 1206 bytes for ML-KEM-768 (27 times more) and 1974 bytes for ML-DSA-65. An ML-KEM-768 ciphertext is 1088 bytes. An ML-DSA-65 signature is 3309 bytes, about 50 times an Ed25519 signature of 64 bytes, and ML-DSA signatures have a fixed size per parameter set. The encoded public keys here are the raw FIPS sizes plus a 22 byte X.509 header: 1184 + 22 = 1206 for ML-KEM-768 and 1952 + 22 = 1974 for ML-DSA-65. Certificate chains, handshakes, database columns and JWT-sized tokens all grow accordingly.

### TLS: the hybrid part arrives in JDK 27

Everything above is for protocols you design yourself. TLS has its own story: [JEP 527](https://openjdk.org/jeps/527), delivered in JDK 27, adds **hybrid** key exchange for TLS 1.3 to `javax.net.ssl`. The named groups are `X25519MLKEM768`, `SecP256r1MLKEM768` and `SecP384r1MLKEM1024`, each combining ML-KEM with a classical ECDHE group, so the connection stays secure if either half is broken. Only `X25519MLKEM768` is on by default, at the front of the preference list, so applications that use the JSSE APIs and do not pin their own groups pick it up without code changes. The other two have to be enabled with `SSLParameters.setNamedGroups` or the `jdk.tls.namedGroups` system property. The program below asks the default `SSLContext` which hybrid groups it offers:

```java run jdk=27
import java.util.Arrays;
import javax.net.ssl.SSLContext;

public class HybridGroups {
    public static void main(String[] args) throws Exception {
        String[] groups = SSLContext.getDefault().getSupportedSSLParameters().getNamedGroups();
        System.out.println(Runtime.version().feature() + ": " + Arrays.stream(groups).filter(g -> g.contains("MLKEM")).toList());
    }
}
```

```text output
27: [X25519MLKEM768]
```

Run on JDK 25, the same program prints `25: []`: the TLS stack of that release has no ML-KEM group, which is why the rest of this document builds on the primitives.

## Gotchas

* **A KEM does not authenticate anyone.** Whoever supplies the public key decides who can read the message. Substitute your own key in transit and you are the man in the middle. In the example, Alice trusts Bob's signing key because both live in one JVM. In reality that key comes from a certificate or a pinned value.
* **The example signs too little.** It signs the ciphertext only. A real handshake signs a transcript that covers both public keys, the ciphertext, the protocol version and a context string, so nothing can be replayed or cut and pasted into another session.
* **Do not use the KEM secret as a key.** It has the algorithm name `Generic`. Run it through HKDF, with a context label and a salt, before it goes anywhere near a cipher.
* **Failure is silent at the KEM layer.** Implicit rejection means `decapsulate` returns normally for a wrong key or a damaged ciphertext. Always follow it with something that authenticates, such as the GCM tag or a signature check. The one exception you can catch is `DecapsulateException`, for input the algorithm cannot even parse.
* **Keys and signatures are big.** See section 5. Check every size limit in your stack (headers, cookies, database fields, QR codes, certificate pinning formats) before you pick a parameter set.
* **Version gates.** ML-KEM and ML-DSA are in JDK 24 or later. The KDF API is a preview API in JDK 24 and compiles without flags only from JDK 25. On JDK 21 to 23 you need a third-party provider.
* **Never log key material.** The example prints only sizes and booleans for a reason: `getEncoded()` on a `SecretKey` or a private key is an easy way to put a secret into a log file.

## When to use it (and when not to)

Use it for **long-lived confidentiality** in protocols you control: encrypted backups and archives, message envelopes, data at rest wrapped for a recipient's public key, and key distribution where harvest-now-decrypt-later is a real threat. The primitives are standardized, they sit behind the standard `KEM`, `KDF`, `Cipher` and `Signature` APIs, and they replace Bouncy Castle for this purpose.

Do not hand-assemble a protocol from these parts for anything that has a standard. For network traffic use TLS, and upgrade to JDK 27 to get hybrid key exchange from JEP 527 without changing code. The hybrid design is the conservative one: ML-KEM is young, and keeping a classical algorithm next to it hedges against a flaw in either. A pure ML-KEM exchange as in this example has no such net. For encrypting to a public key, look at a standardized construction such as Hybrid Public Key Encryption (RFC 9180), which is made of exactly these three ingredients (KEM, KDF, AEAD) and has a vetted key schedule. Treat this document as a way to understand the parts, not as a blueprint for a secure protocol.

That makes the verdict situational: the APIs are production quality, but the example is a teaching sketch, and most applications should get post-quantum protection from their TLS stack rather than from code like this.

## Related

* [095 · An HTTP Server and Client in One File, No Dependencies](095-http-server-and-client.md), whose `HttpClient` runs on the same JSSE stack that JEP 527 upgrades
* [045 · Java as a Scripting Language](../05-modern-language/045-java-scripting.md), because every example here is a single file run with the source launcher

## Sources

* [JEP 496: ML-KEM](https://openjdk.org/jeps/496), [JEP 497: ML-DSA](https://openjdk.org/jeps/497), [JEP 510: Key Derivation Function API](https://openjdk.org/jeps/510) and [JEP 527: Post-Quantum Hybrid Key Exchange for TLS 1.3](https://openjdk.org/jeps/527)
* NIST, [FIPS 203: Module-Lattice-Based Key-Encapsulation Mechanism Standard](https://csrc.nist.gov/pubs/fips/203/final) and [FIPS 204: Module-Lattice-Based Digital Signature Standard](https://csrc.nist.gov/pubs/fips/204/final) (August 2024)
* [`javax.crypto.KEM` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/javax/crypto/KEM.html) and [`javax.crypto.KDF` Javadoc (Java 25)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/javax/crypto/KDF.html)
* H. Krawczyk and P. Eronen, [RFC 5869: HMAC-based Extract-and-Expand Key Derivation Function (HKDF)](https://www.rfc-editor.org/rfc/rfc5869)
