import { createSSRApp, h } from 'vue';
import { renderToString } from 'vue/server-renderer';
import Login from '../src/components/Login.vue';
export async function render() {
  return renderToString(createSSRApp({ render: () => h(Login, { config: { mode: 'demo' } }) }));
}
