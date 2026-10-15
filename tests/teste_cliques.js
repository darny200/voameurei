#!/usr/bin/env node
/*
  Teste de cliques do Baianinho das Passagens (NENHUM clique pode falhar).

  O que ele faz, num iPhone 13 simulado:
   (a) lista TODOS os botões/links visíveis e toca em cada um (cada toque numa página nova),
       anotando o efeito: abriu aba da Aviasales com URL válida? mudou a tela? rolou?
       Controle sem efeito = FALHA. Também abre cada promoção e toca nos botões de dentro,
       toca em cada dia do calendário e no botão de compra que aparece.
   (b) Miami → São Paulo (nov): toca num dia COM preço e num SEM preço e confere o link da data.
   (c) zero erros de console vindos do site (ignora emrldco.com = Travelpayouts Drive).
   (d) nenhum texto "WhatsApp"/"Telegram" na página.
  Tira shot-mobile.png e shot-desktop.png na raiz do site.

  Rodar (precisa do pacote "playwright"):
    NODE_PATH=/caminho/para/node_modules node tests/teste_cliques.js
  Variáveis opcionais: CHROME (executável do Chromium), PORTA (padrão 8765).
*/
const { chromium, devices } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const RAIZ = path.resolve(__dirname, '..');
const PORTA = process.env.PORTA || '8765';
const BASE = 'http://127.0.0.1:' + PORTA + '/';
const CHROME = process.env.CHROME || '/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell';
const MARKER = 'marker=790537';

const resultados = [];   // { nome, ok, efeito }
const errosConsole = [];
function registrar(nome, ok, efeito) {
  resultados.push({ nome, ok, efeito });
  console.log((ok ? 'PASSOU ' : 'FALHOU ') + nome + ' -> ' + efeito);
}
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

function urlAviasalesValida(u) {
  return /^https:\/\/www\.aviasales\.com\//.test(u) && u.includes(MARKER);
}

async function novaPagina(context) {
  const page = await context.newPage();
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const onde = (m.location() && m.location().url) || '';
    if (/emrldco\.com/.test(onde + m.text())) return;
    errosConsole.push(m.text() + ' @ ' + onde);
  });
  page.on('pageerror', (e) => {
    if (/emrldco/.test(String(e.stack || e))) return;
    errosConsole.push('pageerror: ' + e.message);
  });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#calendario .dia:not(.vazio)', { timeout: 15000 });
  await page.waitForSelector('#promos .promo', { timeout: 15000 }).catch(() => {});
  await dormir(500);   // deixa a animação do calendário acabar
  return page;
}

// Instala um "espião" de mudanças na tela
async function armarEspiao(page) {
  await page.evaluate(() => {
    window.__mudou = 0;
    if (window.__obs) window.__obs.disconnect();
    window.__obs = new MutationObserver((l) => { window.__mudou += l.length; });
    window.__obs.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  });
}

// Toca num controle e descobre o que aconteceu
async function tocarEMedir(context, page, loc, nome, opts = {}) {
  await loc.scrollIntoViewIfNeeded();
  await dormir(150);
  const info = await loc.evaluate((el) => ({
    tag: el.tagName.toLowerCase(), href: el.getAttribute('href'), alvo: el.getAttribute('target'),
    rel: el.getAttribute('rel') || '', texto: (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
  }));
  const rotulo = nome + ' [' + info.tag + ' "' + info.texto + '"]';
  if (info.tag === 'a' && (!info.href || info.href === '#')) { registrar(rotulo, false, 'href vazio ou "#"'); return null; }
  const antes = await page.evaluate(() => ({ y: window.scrollY, url: location.href }));
  await armarEspiao(page);
  const abaNova = context.waitForEvent('page', { timeout: 2500 }).catch(() => null);
  await loc.tap();
  const aba = await abaNova;
  if (aba) {
    const u = aba.url() === 'about:blank' ? await aba.waitForURL(/aviasales/, { timeout: 4000 }).then(() => aba.url()).catch(() => aba.url()) : aba.url();
    await aba.close();
    const ok = urlAviasalesValida(u) && info.alvo === '_blank' && /noopener/.test(info.rel)
      && (!opts.esperaUrl || opts.esperaUrl.test(u));
    registrar(rotulo, ok, 'abriu aba nova: ' + u.slice(0, 110) + (ok ? '' : ' (URL/target/rel inválidos)'));
    return { aba: u };
  }
  await dormir(900);
  const depois = await page.evaluate(() => ({ y: window.scrollY, url: location.href, mudou: window.__mudou }));
  const efeitos = [];
  if (depois.url !== antes.url) efeitos.push('mudou o endereço para ' + depois.url.replace(BASE, '/'));
  if (Math.abs(depois.y - antes.y) > 20) efeitos.push('rolou ' + Math.round(antes.y) + '→' + Math.round(depois.y));
  if (depois.mudou > 0) efeitos.push('mudou a tela (' + depois.mudou + ' mudanças)');
  if (opts.esperaAba) { registrar(rotulo, false, 'devia abrir a Aviasales e não abriu'); return null; }
  registrar(rotulo, efeitos.length > 0, efeitos.length ? efeitos.join('; ') : 'NADA aconteceu');
  return { efeitos };
}

// Todos os controles visíveis (a, button, summary), na ordem da página
async function listarControles(page) {
  return page.evaluate(() => {
    const todos = [...document.querySelectorAll('a, button, summary, [role="button"], input[type="submit"]')];
    return todos.map((el, i) => {
      const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
      const visivel = r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !el.closest('[hidden]')
        && (el.checkVisibility ? el.checkVisibility({ visibilityProperty: true }) : true);
      return { i, visivel, desabilitado: !!el.disabled, passado: el.classList.contains('passado'),
        texto: (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 50) };
    });
  });
}
const CONTROLES = 'a, button, summary, [role="button"], input[type="submit"]';

(async () => {
  const servidor = spawn('python3', ['-m', 'http.server', PORTA, '--bind', '127.0.0.1', '--directory', RAIZ], { stdio: 'ignore' });
  await dormir(1200);
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  let codigoSaida = 0;
  try {
    const context = await browser.newContext({ ...devices['iPhone 13'], locale: 'pt-BR', timezoneId: 'America/Sao_Paulo' });
    // A página da Aviasales não precisa carregar de verdade no teste: só conferimos a URL.
    await context.route(/aviasales\.com/, (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<p>ok</p>' }));

    /* ---------- (a) todos os controles visíveis da página inicial ---------- */
    let page = await novaPagina(context);
    const lista = await listarControles(page);
    const visiveis = lista.filter((c) => c.visivel);
    console.log('Controles visíveis na página inicial: ' + visiveis.length);
    for (const c of visiveis.filter((c) => c.desabilitado)) {
      registrar('controle desabilitado #' + c.i + ' "' + c.texto + '"', c.passado, c.passado ? 'dia que já passou (desabilitado de propósito)' : 'desabilitado sem motivo');
    }
    await page.close();
    for (const c of visiveis.filter((c) => !c.desabilitado)) {
      page = await novaPagina(context);
      const loc = page.locator(CONTROLES).nth(c.i);
      const ehDia = await loc.evaluate((el) => el.classList.contains('dia'));
      const r = await tocarEMedir(context, page, loc, 'controle #' + c.i);
      // Dia do calendário: o botão de compra que aparece também tem de funcionar
      if (ehDia && r) {
        const data = await loc.getAttribute('data-data');
        const [, mm, dd] = data.split('-');
        const btn = page.locator('#escolha-link');
        if (!(await btn.isVisible())) registrar('compra do dia ' + data, false, 'botão de compra não apareceu');
        else await tocarEMedir(context, page, btn, '  compra do dia ' + data, { esperaAba: true, esperaUrl: new RegExp('/search/[A-Z]{3}' + dd + mm + '[A-Z]{3}1') });
      }
      await page.close();
    }

    /* ---------- controles escondidos: dentro das promoções ---------- */
    page = await novaPagina(context);
    const nPromos = await page.locator('#promos .promo').count();
    await page.close();
    for (let k = 0; k < nPromos; k++) {
      for (const qual of ['a.btn', 'button.btn']) {
        page = await novaPagina(context);
        const card = page.locator('#promos .promo').nth(k);
        await card.locator('summary').tap();
        await dormir(300);
        const aviso = await card.locator('.aviso-parceiro').innerText().catch(() => '');
        if (qual === 'a.btn' && !/Aviasales.*inglês.*dólar \(US\$\)/s.test(aviso)) registrar('aviso da promoção ' + k, false, 'sem aviso de inglês/dólar');
        await tocarEMedir(context, page, card.locator(qual), 'promoção ' + k + ' ' + qual, qual === 'a.btn' ? { esperaAba: true } : {});
        await page.close();
      }
    }

    /* ---------- (b) Miami → São Paulo, novembro ---------- */
    page = await novaPagina(context);
    await page.selectOption('#origem', 'MIA');
    await page.dispatchEvent('#origem', 'change');
    await page.selectOption('#destino', 'SAO');
    const mesNov = await page.$$eval('#mes option', (os) => (os.find((o) => o.value.endsWith('-11')) || os[1] || os[0]).value);
    await page.selectOption('#mes', mesNov);
    await page.locator('#btn-buscar').tap();
    await dormir(800);
    const comPreco = page.locator('#calendario .dia:not(.sem):not(.passado):not(.vazio)').first();
    const semPreco = page.locator('#calendario .dia.sem').first();
    const qtdCom = await page.locator('#calendario .dia:not(.sem):not(.passado):not(.vazio)').count();
    const qtdSem = await page.locator('#calendario .dia.sem').count();
    console.log('Miami→São Paulo ' + mesNov + ': ' + qtdCom + ' dias com preço, ' + qtdSem + ' sem preço');
    for (const [loc, tipo] of [[comPreco, 'COM preço'], [semPreco, 'SEM preço']]) {
      if (!(await loc.count())) { registrar('MIA→SAO dia ' + tipo, false, 'não existe dia ' + tipo + ' neste mês'); continue; }
      const data = await loc.getAttribute('data-data');
      const [, mm, dd] = data.split('-');
      await loc.tap(); await dormir(400);
      const btn = page.locator('#escolha-link');
      const visivel = await btn.isVisible();
      const href = visivel ? await btn.getAttribute('href') : '';
      const texto = visivel ? (await btn.innerText()).trim() : '';
      const cartao = (await page.locator('#escolha').innerText()).replace(/\s+/g, ' ');
      const esperado = tipo === 'SEM preço'
        ? href === 'https://www.aviasales.com/search/MIA' + dd + mm + 'SAO1?marker=790537' && texto === 'Ver voos deste dia' && /Preço ao vivo na Aviasales/.test(cartao)
        : new RegExp('^https://www\\.aviasales\\.com/search/[A-Z]{3}' + dd + mm + '[A-Z]{3}1\\?.*marker=790537').test(href) && texto === 'Comprar este dia';
      const temAviso = /inglês.*dólar \(US\$\)/.test(cartao);
      registrar('MIA→SAO dia ' + tipo + ' (' + data + ')', visivel && esperado && temAviso, 'botão "' + texto + '" → ' + href.slice(0, 100));
      if (visivel) await tocarEMedir(context, page, btn, '  MIA→SAO abrir ' + tipo, { esperaAba: true });
    }
    const poucos = await page.locator('#poucos').isVisible();
    console.log('Linha "poucos preços" visível: ' + poucos + ' (deve ser ' + (qtdCom < 5) + ')');
    if (poucos !== (qtdCom < 5)) registrar('linha "poucos preços"', false, 'visível=' + poucos + ' com ' + qtdCom + ' dias');
    await page.screenshot({ path: path.join(RAIZ, 'shot-mobile.png'), fullPage: true });
    await page.close();

    /* ---------- rota sem nenhum preço: sugestões + calendário continuam úteis ---------- */
    const json = JSON.parse(fs.readFileSync(path.join(RAIZ, 'precos.json'), 'utf8'));
    let vazia = null;
    for (const [rota, meses] of Object.entries(json.rotas)) for (const m of json.meses) if (!Object.keys(meses[m] || {}).length && !vazia) vazia = [rota, m];
    if (vazia) {
      const [o, d] = vazia[0].split('-');
      const preparar = async () => {
        const p = await novaPagina(context);
        await p.selectOption('#origem', o); await p.dispatchEvent('#origem', 'change');
        await p.selectOption('#destino', d); await p.selectOption('#mes', vazia[1]);
        await p.locator('#btn-buscar').tap(); await dormir(800);
        return p;
      };
      page = await preparar();
      const calVisivel = await page.locator('#calendario').isVisible();
      registrar('rota sem preço ' + vazia.join(' ') + ': calendário visível', calVisivel, calVisivel ? 'ok' : 'calendário escondido');
      const nSug = await page.locator('#sugestoes button').count();
      await page.close();
      for (let k = 0; k < nSug; k++) {
        page = await preparar();
        await tocarEMedir(context, page, page.locator('#sugestoes button').nth(k), 'sugestão ' + k + ' (rota sem preço)');
        await page.close();
      }
      page = await preparar();
      const dia = page.locator('#calendario .dia.sem').first();
      if (await dia.count()) {
        await tocarEMedir(context, page, dia, 'dia "ver" na rota sem preço');
        await tocarEMedir(context, page, page.locator('#escolha-link'), '  ver voos (rota sem preço)', { esperaAba: true });
      }
      await page.close();
    } else console.log('(nenhuma rota/mês totalmente vazia para testar as sugestões)');

    /* ---------- (d) sem WhatsApp/Telegram; links seguros ---------- */
    page = await novaPagina(context);
    const html = await page.evaluate(() => document.documentElement.outerHTML);
    const texto = await page.evaluate(() => document.body.innerText);
    const proibido = /whats\s*app|telegram/i.test(html) || /whats\s*app|telegram/i.test(texto);
    registrar('sem "WhatsApp"/"Telegram" na página', !proibido, proibido ? 'ainda aparece' : 'nenhuma ocorrência');
    const linksRuins = await page.$$eval('a', (as) => as.filter((a) => {
      const h = a.getAttribute('href') || '';
      if (!h || h === '#') return true;
      if (/^http:\/\//.test(h)) return true;
      if (/aviasales/.test(h) && (a.target !== '_blank' || !/noopener/.test(a.rel))) return true;
      return false;
    }).map((a) => a.outerHTML.slice(0, 120)));
    registrar('links: nenhum href vazio/"#"/http:// e compra com target=_blank rel=noopener', !linksRuins.length, linksRuins.length ? linksRuins.join(' | ') : 'ok');
    const avisos = await page.locator('.embarque .aviso-parceiro').count();
    registrar('aviso de inglês/dólar antes do botão principal', avisos === 1, avisos + ' aviso(s)');
    await page.close();

    const desk = await browser.newContext({ viewport: { width: 1366, height: 900 }, locale: 'pt-BR', timezoneId: 'America/Sao_Paulo' });
    const pd = await novaPagina(desk);
    await pd.screenshot({ path: path.join(RAIZ, 'shot-desktop.png'), fullPage: true });
    await desk.close();

    /* ---------- (c) erros de console ---------- */
    registrar('zero erros de console do site', errosConsole.length === 0, errosConsole.length ? errosConsole.slice(0, 5).join(' | ') : 'nenhum');

    const falhas = resultados.filter((r) => !r.ok);
    console.log('\nRESUMO: ' + resultados.length + ' verificações, ' + (resultados.length - falhas.length) + ' passaram, ' + falhas.length + ' falharam.');
    falhas.forEach((f) => console.log('  FALHA: ' + f.nome + ' -> ' + f.efeito));
    codigoSaida = falhas.length ? 1 : 0;
  } catch (e) {
    console.error('ERRO NO TESTE:', e);
    codigoSaida = 2;
  } finally {
    await browser.close();
    servidor.kill();
    process.exit(codigoSaida);
  }
})();
