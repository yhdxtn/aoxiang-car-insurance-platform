// 从实际 WXML/WXSS 生成静态视觉检查页；不是微信运行时，也不替代真机验收。
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const output = path.join(root, "preview");
fs.mkdirSync(output, { recursive: true });
const escape = (value) =>
  String(value == null ? "" : value).replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
function expr(value, data) {
  try {
    return Function(
      ...Object.keys(data),
      "return (" + value + ")",
    )(...Object.values(data));
  } catch (_) {
    return undefined;
  }
}
function interpolate(text, data) {
  return text.replace(/{{(.*?)}}/g, (_, expression) =>
    escape(expr(expression, data)),
  );
}
function parse(source) {
  const rootNode = { name: "root", attrs: {}, children: [] },
    stack = [rootNode];
  const regex = /<(\/?)([a-zA-Z][\w-]*)((?:[^"'>]|"[^"]*"|'[^']*')*)>/g;
  let last = 0,
    match;
  while ((match = regex.exec(source))) {
    if (match.index > last)
      stack[stack.length - 1].children.push(source.slice(last, match.index));
    if (match[1]) stack.pop();
    else {
      const attrs = {};
      for (const attribute of match[3].matchAll(/([\w:-]+)(?:="([^"]*)")?/g))
        attrs[attribute[1]] = attribute[2] == null ? true : attribute[2];
      const node = { name: match[2], attrs, children: [] };
      stack[stack.length - 1].children.push(node);
      if (!match[0].endsWith("/>")) stack.push(node);
    }
    last = regex.lastIndex;
  }
  return rootNode;
}
function evaluateAttribute(value, data) {
  if (typeof value !== "string") return value;
  const exact = /^{{(.*)}}$/.exec(value);
  return exact ? expr(exact[1], data) : interpolate(value, data);
}
function renderChildren(nodes, data) {
  let out = "",
    previousIf = false,
    branch = false;
  for (const node of nodes) {
    if (typeof node === "string") {
      out += interpolate(node, data);
      continue;
    }
    if (node.attrs["wx:if"] !== undefined) {
      previousIf = true;
      branch = !!evaluateAttribute(node.attrs["wx:if"], data);
      if (!branch) continue;
    } else if (node.attrs["wx:elif"] !== undefined) {
      if (!previousIf || branch) continue;
      branch = !!evaluateAttribute(node.attrs["wx:elif"], data);
      if (!branch) continue;
    } else if (node.attrs["wx:else"] !== undefined) {
      if (!previousIf || branch) continue;
      branch = true;
    } else {
      previousIf = false;
      branch = false;
    }
    if (node.attrs["wx:for"]) {
      const list = evaluateAttribute(node.attrs["wx:for"], data) || [];
      list.forEach((item, index) => {
        out += renderNode(node, Object.assign({}, data, { item, index }));
      });
    } else out += renderNode(node, data);
  }
  return out;
}
function renderNode(node, data) {
  if (node.name === "assistant-avatar") {
    const componentData = {
      size: evaluateAttribute(node.attrs.size || "normal", data),
      service: evaluateAttribute(node.attrs.service || false, data),
    };
    return (
      '<div class="assistant-avatar">' +
      renderChildren(
        parse(
          fs.readFileSync(
            path.join(root, "components/assistant-avatar/index.wxml"),
            "utf8",
          ),
        ).children,
        componentData,
      ).replace(
        /class="([^"]*)"/g,
        (_, classes) =>
          'class="' +
          classes
            .split(/\s+/)
            .filter(Boolean)
            .map((name) => "bot-" + name)
            .join(" ") +
          '"',
      ) +
      "</div>"
    );
  }
  if (node.name === "block" || node.name === "root")
    return renderChildren(node.children, data);
  const tags = {
    view: "div",
    text: "span",
    image: "img",
    "scroll-view": "div",
    picker: "div",
    progress: "progress",
  };
  const name = tags[node.name] || node.name;
  const attributes = Object.entries(node.attrs)
    .filter(([key]) =>
      [
        "class",
        "style",
        "src",
        "id",
        "value",
        "placeholder",
        "disabled",
        "maxlength",
      ].includes(key),
    )
    .map(([key, value]) => {
      const resolved = evaluateAttribute(value, data);
      if (key === "disabled") return resolved ? "disabled" : "";
      return (
        key +
        '="' +
        escape(resolved).replace(
          /([\d.]+)rpx/g,
          (_, n) => Number(n) * 0.52 + "px",
        ) +
        '"'
      );
    })
    .join(" ");
  return (
    "<" +
    name +
    " " +
    attributes +
    ">" +
    renderChildren(node.children, data) +
    (["img", "input"].includes(name) ? "" : "</" + name + ">")
  );
}
const baseCss =
  fs.readFileSync(path.join(root, "app.wxss"), "utf8") +
  fs
    .readFileSync(
      path.join(root, "components/assistant-avatar/index.wxss"),
      "utf8",
    )
    .replace(/\.([A-Za-z_][\w-]*)/g, ".bot-$1");
const vehicle = {
  plateNo: "云A·示例",
  vin: "SAMPLE00000000000",
  ownerName: "演示用户",
  useNature: "家庭自用",
  seatCount: 5,
};
const fixtures = {
  home: {
    mode: "demo",
    loading: false,
    error: "",
    loggedIn: false,
    sessions: [],
  },
  assistant: {
    mode: "demo",
    loading: false,
    busy: false,
    error: "",
    stage: 1,
    vehicleTypeLabel: "家用车",
    session: { id: "demo", status: "BOT" },
    canSend: true,
    sessionStatus: "助手服务中",
    greeting: "你好，我是你的车险助手。先上传行驶证，我来帮你整理车辆信息。",
    messages: [
      {
        id: "m1",
        user: true,
        content: "已上传行驶证",
        fileId: "f1",
        fileName: "行驶证.jpg",
        imagePath: "",
      },
      {
        id: "m2",
        user: false,
        content: "车辆信息已保存，请核对后选择泰康报价方案。",
      },
    ],
    hasVehicle: true,
    vehicleSummary: vehicle,
    vehicle,
    quote: null,
    isMotorcycle: false,
    isManualVehicle: false,
    messageText: "",
    showForm: false,
    showPrivacy: false,
  },
  orders: {
    mode: "demo",
    loggedIn: true,
    items: [
      {
        id: "demo",
        plateNo: "云A·示例",
        statusLabel: "待人工核对",
        typeLabel: "家用车",
        customerName: "演示用户",
        demo: true,
        orderNo: "TK-PREVIEW-0001",
        formattedTime: "2026-11-12 20:30",
        formattedPremium: "3796.50",
      },
    ],
    loading: false,
    error: "",
    search: "",
    status: "",
    hasMore: false,
    tabs: [
      { value: "", label: "全部" },
      { value: "PENDING_REVIEW", label: "待核对" },
      { value: "PROCESSING", label: "办理中" },
      { value: "COMPLETED", label: "已完成" },
    ],
  },
};
for (const [name, data] of Object.entries(fixtures)) {
  const markup = fs.readFileSync(
    path.join(root, "pages", name, "index.wxml"),
    "utf8",
  );
  const css = (
    baseCss +
    fs.readFileSync(path.join(root, "pages", name, "index.wxss"), "utf8")
  )
    .replace(/(?<![\w.-])page\s*\{/g, "body{")
    .replace(/:host/g, ".assistant-avatar")
    .replace(/([\d.]+)rpx/g, (_, n) => Number(n) * 0.52 + "px");
  const title =
    name === "assistant"
      ? "翱翔车险报价"
      : name === "orders"
        ? "我的订单"
        : "翱翔车险报价";
  const html =
    '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' +
    title +
    " · 视觉检查</title><style>body{margin:0;width:390px;min-height:100vh}button,input,textarea{font-family:inherit;border:0;outline:none}button{cursor:pointer}input{outline:none}img{object-fit:contain}.native-bar{height:54px;padding:0 16px;display:flex;align-items:center;justify-content:space-between;font-weight:700;font-size:20px;background:#fff8ee}.native-back{font-size:29px;font-weight:400}.native-menu{font-size:15px;border:1px solid #e7e0d7;padding:5px 12px;border-radius:25px;letter-spacing:5px}" +
    css +
    'button{display:flex;align-items:center;justify-content:center;min-height:44px;box-sizing:border-box}.assistant-avatar{flex-shrink:0}input{box-sizing:border-box}body{font-family:"Noto Sans CJK SC",sans-serif}' +
    '</style></head><body><div class="native-bar"><span class="native-back">‹</span><span>' +
    title +
    '</span><span class="native-menu">•••◉</span></div>' +
    renderChildren(parse(markup).children, data) +
    "</body></html>";
  fs.writeFileSync(path.join(output, name + ".html"), html);
}
console.log(
  "Static visual previews created in preview/. Fixtures are fictional, no API calls are made.",
);
