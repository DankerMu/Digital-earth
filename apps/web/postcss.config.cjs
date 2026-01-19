function optionalRequire(name) {
  try {
    // eslint-disable-next-line global-require, import/no-dynamic-require
    return require(name);
  } catch {
    return null;
  }
}

const tailwindcss = optionalRequire('tailwindcss');
const autoprefixer = optionalRequire('autoprefixer');

module.exports = {
  plugins: [tailwindcss?.(), autoprefixer?.()].filter(Boolean),
};
