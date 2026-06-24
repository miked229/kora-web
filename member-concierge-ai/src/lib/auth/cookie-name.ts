/**
 * Nombre de la cookie de sesión del socio, en un módulo aparte (sin
 * `server-only` ni dependencias de Node) para poder importarlo desde el
 * middleware del edge sin arrastrar el cliente de sesión.
 */
export const SESSION_COOKIE_NAME = "mc_session";
