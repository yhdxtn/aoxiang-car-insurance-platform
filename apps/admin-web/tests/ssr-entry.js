import { createSSRApp, h } from 'vue';
import { renderToString } from 'vue/server-renderer';
import Login from '../src/views/Login.vue';
import Dashboard from '../src/views/Dashboard.vue';
export async function render(name = 'login') {
  const component = name === 'dashboard' ? Dashboard : Login;
  const props =
    name === 'dashboard'
      ? { user: { name: '管理员' }, notify: () => {} }
      : { config: { mode: 'demo' } };
  return renderToString(createSSRApp({ render: () => h(component, props) }));
}
