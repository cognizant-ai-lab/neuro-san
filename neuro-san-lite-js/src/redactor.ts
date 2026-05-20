// Port of neuro_san_client/redactor.py
// sly_data redaction — the CORS-equivalent for the Agent Web protocol.
//
// Keep behavior bit-for-bit identical to the Python module; both packages
// are tested with the same input/output cases.

import type { Json, SlyData } from "./types.js";

type AllowRule =
    | boolean
    | string[]
    | Record<string, boolean | string>
    | null
    | undefined;

function getDotted(spec: Record<string, Json>, dottedKey: string): Json | undefined {
    let node: Json = spec;
    for (const part of dottedKey.split(".")) {
        if (node === null || typeof node !== "object" || Array.isArray(node)) {
            return undefined;
        }
        const next: Json | undefined = (node as Record<string, Json>)[part];
        if (next === undefined || next === null) {
            return undefined;
        }
        node = next;
    }
    return node;
}

function maybeEmpty(d: SlyData, allowEmpty: boolean): SlyData | null {
    if (!allowEmpty && Object.keys(d).length === 0) {
        return null;
    }
    return d;
}

/**
 * Filter `slyData` according to the allow rule found at one of the dotted
 * `configKeys` paths within `agentSpec`. Later entries in `configKeys` have
 * higher precedence.
 */
export function redact(
    agentSpec: Record<string, Json> | null | undefined,
    slyData: SlyData | null | undefined,
    configKeys: string[],
    allowEmptyDict: boolean = true,
): SlyData | null {
    if (slyData === null || slyData === undefined || typeof slyData !== "object" || Array.isArray(slyData)) {
        slyData = {};
    }

    // Resolve the rule, with later configKeys winning over earlier ones.
    let rule: AllowRule = undefined;
    if (agentSpec && typeof agentSpec === "object" && !Array.isArray(agentSpec)) {
        for (const key of configKeys) {
            const found = getDotted(agentSpec, key);
            if (found !== undefined && found !== null) {
                rule = found as AllowRule;
            }
        }
    }

    // Empty / missing rule: deny everything (security by default).
    if (rule === undefined || rule === null || rule === false) {
        return maybeEmpty({}, allowEmptyDict);
    }
    if (Array.isArray(rule) && rule.length === 0) {
        return maybeEmpty({}, allowEmptyDict);
    }
    if (typeof rule === "object" && !Array.isArray(rule) && Object.keys(rule).length === 0) {
        return maybeEmpty({}, allowEmptyDict);
    }

    // Plain true: allow everything through unchanged.
    if (rule === true) {
        return maybeEmpty({ ...slyData }, allowEmptyDict);
    }

    // List form: turn into dict with true values for canonical processing.
    let ruleMap: Record<string, boolean | string>;
    if (Array.isArray(rule)) {
        ruleMap = {};
        for (const k of rule) {
            if (typeof k === "string") {
                ruleMap[k] = true;
            }
        }
    } else if (typeof rule === "object") {
        ruleMap = rule as Record<string, boolean | string>;
    } else {
        // Unrecognized rule shape: deny everything.
        return maybeEmpty({}, allowEmptyDict);
    }

    const out: SlyData = {};
    for (const [sourceKey, dest] of Object.entries(ruleMap)) {
        if (!(sourceKey in slyData)) {
            continue;
        }
        const value = (slyData as SlyData)[sourceKey];
        if (typeof dest === "boolean") {
            if (dest) {
                out[sourceKey] = value;
            }
            // else: explicitly denied
        } else if (typeof dest === "string" && dest) {
            // Rename: copy value to a different key name.
            out[dest] = value;
        }
        // Any other value type is treated as denied (defensive).
    }
    return maybeEmpty(out, allowEmptyDict);
}
