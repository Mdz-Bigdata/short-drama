/** Product naming, written once so the login page, the lobby and the assistant agree.
 *
 * These are live bindings: `applyBrand` sets them from the deployment's appearance before the
 * interface first renders (src/appearance), so every importer reads the deployment's brand.
 */
export const DEFAULT_PRODUCT_NAME = 'Novara';
export const PRODUCT_VERSION = '1.0';
export let PRODUCT_NAME = DEFAULT_PRODUCT_NAME;
export let PRODUCT_TITLE = `${PRODUCT_NAME} ${PRODUCT_VERSION}`;
export let NOVARA_AGENT_NAME = `${PRODUCT_NAME} AI`;

/** Use the deployment's brand (null: the built-in one). A custom brand is shown without the version. */
export function applyBrand(brandName: string | null, assistantName: string | null = null): void {
  const custom = (brandName ?? '').trim();
  PRODUCT_NAME = custom || DEFAULT_PRODUCT_NAME;
  PRODUCT_TITLE = custom ? custom : `${DEFAULT_PRODUCT_NAME} ${PRODUCT_VERSION}`;
  NOVARA_AGENT_NAME = (assistantName ?? '').trim() || `${PRODUCT_NAME} AI`;
}
