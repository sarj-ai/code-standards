// vitest: shared-module-graph
import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/jsx-no-forbidden-nesting.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

ruleTester({ lang: "tsx" }).run("jsx-no-forbidden-nesting", rule, {
  valid: [
    "<constructor><span>text</span></constructor>",
    "<hasOwnProperty><div /></hasOwnProperty>",
    "<p><span>text</span><a href='/x'>link</a></p>",
    "<div><p>one</p><p>two</p></div>",
    "<ul><li>one</li></ul>",
    "<ol>{items.map((item) => <li key={item}>{item}</li>)}</ol>",
    "<menu><li><button>Run</button></li></menu>",
    "<table><tbody><tr><td>cell</td></tr></tbody></table>",
    "<table><thead><tr><th>head</th></tr></thead></table>",
    "<table><caption>c</caption><colgroup><col /></colgroup></table>",
    "<dl><dt>term</dt><dd>detail</dd></dl>",
    "<li><ul><li>nested</li></ul></li>",
    "<form><fieldset><input name='q' /></fieldset></form>",
    "<button><span>Save</span><svg><path d='M0' /></svg></button>",
    "<button><a>no href is not interactive</a></button>",
    "<button><input type='hidden' name='id' /></button>",
    "<button><input {...props} /></button>",
    "<button><input type={type} /></button>",
    "<a href='/x'><img src='a.png' alt='' /></a>",
    "<a href='/x'><video src='v.mp4' /></a>",
    "<a href='/x'><video controls={false} src='v.mp4' /></a>",
    "<a href='/x'><audio {...props} /></a>",
    "<button><a {...props}>spread may omit href</a></button>",
    "<p><button><div>button scope</div></button></p>",
    "<p><Card><div>component is opaque</div></Card></p>",
    "<a href='/x'><Tooltip content={<a href='/y'>tip</a>} /></a>",
    "<a href='/x'><Button>component</Button></a>",
    "<p><motion.div>member expression</motion.div></p>",
    "<p><Tag>alias</Tag></p>",
    "const Tag = 'div'; <p><Tag>alias</Tag></p>",
    "const inner = <div />; <p>{inner}</p>",
    "<p>{renderBlock(<div />)}</p>",
    "<p>{items.forEach(() => <div />)}</p>",
    "<p>{() => <div />}</p>",
    "<p>{items.map((item) => <div key={item} />)[0]}</p>",
    "function Block() { return <div />; } <p><Block /></p>",
    "<p>{items.map(function () { const block = <div />; return <span>{block}</span>; })}</p>",
    "<p>{items.map(() => { const render = () => { return <div />; }; return render(); })}</p>",
    "<p dangerouslySetInnerHTML={{ __html: '<div></div>' }} />",
    "<div><p /></div>",
    "<a href='/x'><svg><a href='#frag'><text>svg link</text></a></svg></a>",
    "<p><svg><foreignObject><div>fresh context</div></foreignObject></svg></p>",
    "<p><math><mi>x</mi></math></p>",
    "<table><template><tr><td /></tr></template></table>",
    "<p><my-element>custom</my-element></p>",
    "<label>Name <input name='n' /></label>",
    "<html><head><title>t</title></head><body><main /></body></html>",
    "function Row() { return <tr><td /></tr>; }",
    "function Item() { return <li>outside visible list</li>; }",
    "<ul><Item><li>component parent</li></Item></ul>",
    "<div><Fragment><li>component fragment</li></Fragment></div>",
    {
      filename: "generated/view.tsx",
      code: "<p><div /></p>",
    },
  ],
  invalid: [
    {
      code: "<p><div>block</div></p>",
      errors: [{ messageId: "parserDescendant", data: { tag: "div", ancestor: "p" } }],
    },
    {
      code: "<p><span><ul><li /></ul></span></p>",
      errors: [{ messageId: "parserDescendant", data: { tag: "ul", ancestor: "p" } }],
    },
    {
      code: "<p><my-element><div /></my-element></p>",
      errors: [{ messageId: "parserDescendant", data: { tag: "div", ancestor: "p" } }],
    },
    {
      code: "<a href='/x'><span><a href='/y'>inner</a></span></a>",
      errors: [{ messageId: "parserDescendant", data: { tag: "a", ancestor: "a" } }],
    },
    {
      code: "<button><span><button>inner</button></span></button>",
      errors: [{ messageId: "parserDescendant", data: { tag: "button", ancestor: "button" } }],
    },
    {
      code: "<form><div><form /></div></form>",
      errors: [{ messageId: "parserDescendant", data: { tag: "form", ancestor: "form" } }],
    },
    {
      code: "<h1><h2>nested heading</h2></h1>",
      errors: [{ messageId: "parserChild", data: { tag: "h2", ancestor: "h1" } }],
    },
    {
      code: "<table><tr><td /></tr></table>",
      errors: [{ messageId: "tableRow", data: { tag: "tr", ancestor: "table" } }],
    },
    {
      code: "<tbody><td /></tbody>",
      errors: [{ messageId: "parserChild", data: { tag: "td", ancestor: "tbody" } }],
    },
    {
      code: "<tr><div /></tr>",
      errors: [{ messageId: "parserChild", data: { tag: "div", ancestor: "tr" } }],
    },
    {
      code: "<select><input /></select>",
      errors: [{ messageId: "parserChild", data: { tag: "input", ancestor: "select" } }],
    },
    {
      code: "<div><td /></div>",
      errors: [{ messageId: "parserChild", data: { tag: "td", ancestor: "div" } }],
    },
    {
      code: "<li><span><li /></span></li>",
      errors: [{ messageId: "parserDescendant", data: { tag: "li", ancestor: "li" } }],
    },
    {
      code: "<li><div><li>div keeps list-item scope</li></div></li>",
      errors: [{ messageId: "parserDescendant", data: { tag: "li", ancestor: "li" } }],
    },
    {
      code: "<tr><svg /></tr>",
      errors: [{ messageId: "parserChild", data: { tag: "svg", ancestor: "tr" } }],
    },
    {
      code: "<div><li>stray</li></div>",
      errors: [{ messageId: "contentModel", data: { tag: "li", ancestor: "div" } }],
    },
    {
      code: "<ul><div><li /></div></ul>",
      errors: [{ messageId: "contentModel", data: { tag: "li", ancestor: "div" } }],
    },
    {
      code: "<button><a href='/x'>link</a></button>",
      errors: [{ messageId: "contentModel", data: { tag: "a", ancestor: "button" } }],
    },
    {
      code: "<a href='/x'><div><button>Buy</button></div></a>",
      errors: [{ messageId: "contentModel", data: { tag: "button", ancestor: "a" } }],
    },
    {
      code: "<a href='/x'><input type='checkbox' /></a>",
      errors: [{ messageId: "contentModel", data: { tag: "input", ancestor: "a" } }],
    },
    {
      code: "<button><input /></button>",
      errors: [{ messageId: "contentModel", data: { tag: "input", ancestor: "button" } }],
    },
    {
      code: "<a href='/x'><video controls src='v.mp4' /></a>",
      errors: [{ messageId: "contentModel", data: { tag: "video", ancestor: "a" } }],
    },
    {
      code: "<a href='/x'><select /></a>",
      errors: [{ messageId: "contentModel", data: { tag: "select", ancestor: "a" } }],
    },
    {
      code: "<label><span><label>inner</label></span></label>",
      errors: [{ messageId: "contentModel", data: { tag: "label", ancestor: "label" } }],
    },
    {
      code: "<a {...props}><a href='/y' /></a>",
      errors: [{ messageId: "parserDescendant", data: { tag: "a", ancestor: "a" } }],
    },
    {
      code: "<p>{open && <div />}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{open ? <div /> : <span />}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{label ?? <div />}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p><><div /></></p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{[<div key='a' />]}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{(<div />) as ReactNode}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{items.map((item) => <div key={item} />)}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{items?.flatMap((item) => [<div key={item} />])}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{items.map(function (item) { if (item) { return <div key={item} />; } return null; })}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{items.map((item) => { try { return <div key={item} />; } catch { return null; } })}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p>{items.map((item) => { for (const part of item) { return <div key={part} />; } return null; })}</p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<table>{rows.map((row) => <tr key={row} />)}</table>",
      errors: [{ messageId: "tableRow" }],
    },
    {
      code: "<p><div dangerouslySetInnerHTML={{ __html: html }} /></p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<p><svg><foreignObject><div><p><div /></p></div></foreignObject></svg></p>",
      errors: [{ messageId: "parserDescendant" }],
    },
    {
      code: "<button><span /><div><button /></div></button>",
      errors: [{ messageId: "parserDescendant" }],
    },
  ],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["jsx-no-forbidden-nesting"])).resolves.toBeGreaterThan(0);
});
