import { getCachedRegex } from "./regex.js";
export function escapeForRegex(word) {
    return word.replace(getCachedRegex(/[$()*+./?[\\\]^{|}-]/g), "\\$&");
}