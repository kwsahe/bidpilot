/** `node --import` 로 먼저 실행되어 별칭 훅을 등록한다. `_alias.mjs` 설명 참고. */
import { register } from "node:module";

register("./_alias.mjs", import.meta.url);
