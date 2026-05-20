// Vitest unit tests for src/redactor.ts.
// Mirrors neuro-san-client/tests/unit/test_redactor.py case-for-case so
// behavior cannot drift between the two implementations.

import { describe, expect, it } from "vitest";
import { redact } from "../src/redactor.js";

const SLY = {
    passenger_email: "bob@example.com",
    browser_secret: "must-not-leak",
    last_booking_code: "HOLD-XYZ",
};

const CONFIG_KEYS = ["allow.to_downstream.sly_data"];

describe("redact: deny by default", () => {
    it("missing spec", () => {
        expect(redact(null, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("empty spec", () => {
        expect(redact({}, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("missing path", () => {
        expect(redact({ name: "foo" }, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("explicit false", () => {
        const spec = { allow: { to_downstream: { sly_data: false } } };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("empty dict", () => {
        const spec = { allow: { to_downstream: { sly_data: {} } } };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("empty list", () => {
        const spec = { allow: { to_downstream: { sly_data: [] } } };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({});
    });
});

describe("redact: allow all", () => {
    it("true passes everything", () => {
        const spec = { allow: { to_downstream: { sly_data: true } } };
        const out = redact(spec, SLY, CONFIG_KEYS);
        expect(out).toEqual(SLY);
        // Must be a copy, not the original.
        expect(out).not.toBe(SLY);
    });
});

describe("redact: list form", () => {
    it("simple allowlist", () => {
        const spec = { allow: { to_downstream: { sly_data: ["passenger_email"] } } };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            passenger_email: "bob@example.com",
        });
    });

    it("multiple keys", () => {
        const spec = {
            allow: {
                to_downstream: {
                    sly_data: ["passenger_email", "last_booking_code"],
                },
            },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            passenger_email: "bob@example.com",
            last_booking_code: "HOLD-XYZ",
        });
    });

    it("listed key missing from sly is skipped", () => {
        const spec = { allow: { to_downstream: { sly_data: ["not_in_sly"] } } };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("list with non-string values ignored", () => {
        const spec = {
            allow: {
                to_downstream: { sly_data: ["passenger_email", 42, null] as any },
            },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            passenger_email: "bob@example.com",
        });
    });
});

describe("redact: dict form", () => {
    it("explicit true allows", () => {
        const spec = {
            allow: { to_downstream: { sly_data: { passenger_email: true } } },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            passenger_email: "bob@example.com",
        });
    });

    it("explicit false denies", () => {
        const spec = {
            allow: {
                to_downstream: {
                    sly_data: { passenger_email: true, browser_secret: false },
                },
            },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            passenger_email: "bob@example.com",
        });
    });

    it("string value renames", () => {
        const spec = {
            allow: {
                to_downstream: { sly_data: { passenger_email: "user_email" } },
            },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            user_email: "bob@example.com",
        });
    });

    it("dict with missing keys skips", () => {
        const spec = {
            allow: {
                to_downstream: {
                    sly_data: { passenger_email: true, absent: true },
                },
            },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({
            passenger_email: "bob@example.com",
        });
    });

    it("unknown value type denies", () => {
        const spec = {
            allow: {
                to_downstream: { sly_data: { passenger_email: 42 as any } },
            },
        };
        expect(redact(spec, SLY, CONFIG_KEYS)).toEqual({});
    });
});

describe("redact: precedence", () => {
    it("later config key wins", () => {
        const spec = {
            allow: {
                sly_data: ["browser_secret"],
                to_downstream: { sly_data: ["passenger_email"] },
            },
        };
        const out = redact(spec, SLY, [
            "allow.sly_data",
            "allow.to_downstream.sly_data",
        ]);
        expect(out).toEqual({ passenger_email: "bob@example.com" });
    });

    it("falls back to earlier when later missing", () => {
        const spec = { allow: { sly_data: ["passenger_email"] } };
        const out = redact(spec, SLY, [
            "allow.sly_data",
            "allow.to_downstream.sly_data",
        ]);
        expect(out).toEqual({ passenger_email: "bob@example.com" });
    });
});

describe("redact: allowEmptyDict flag", () => {
    it("empty returns dict by default", () => {
        expect(redact({}, SLY, CONFIG_KEYS)).toEqual({});
    });

    it("empty returns null when flag set", () => {
        expect(redact({}, SLY, CONFIG_KEYS, false)).toBeNull();
    });

    it("nonempty unaffected by flag", () => {
        const spec = { allow: { to_downstream: { sly_data: true } } };
        expect(redact(spec, SLY, CONFIG_KEYS, false)).toEqual(SLY);
    });
});

describe("redact: sly_data validation", () => {
    it("non-object sly_data treated as empty", () => {
        const spec = { allow: { to_downstream: { sly_data: true } } };
        expect(redact(spec, "not an object" as any, CONFIG_KEYS)).toEqual({});
    });

    it("null sly_data", () => {
        const spec = { allow: { to_downstream: { sly_data: true } } };
        expect(redact(spec, null, CONFIG_KEYS)).toEqual({});
    });

    it("undefined sly_data", () => {
        const spec = { allow: { to_downstream: { sly_data: true } } };
        expect(redact(spec, undefined, CONFIG_KEYS)).toEqual({});
    });
});

describe("redact: preserves value types", () => {
    it("values can be any JSON type", () => {
        const sly = {
            string: "hi",
            number: 42,
            list: [1, 2, 3],
            dict: { nested: true },
            bool: false,
        };
        const spec = { allow: { to_downstream: { sly_data: true } } };
        expect(redact(spec, sly, CONFIG_KEYS)).toEqual(sly);
    });
});

describe("redact: doesn't mutate the source", () => {
    it("original sly_data is untouched", () => {
        const sly = { passenger_email: "bob@example.com", secret: "x" };
        const original = { ...sly };
        const spec = {
            allow: { to_downstream: { sly_data: ["passenger_email"] } },
        };
        redact(spec, sly, CONFIG_KEYS);
        expect(sly).toEqual(original);
    });
});
