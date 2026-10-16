#!/usr/bin/env node
/*
  Teste de cliques do Baianinho das Passagens (NENHUM clique pode falhar).

  O que ele faz, num iPhone 13 simulado:
   (a) lista TODOS os botões/links visíveis e toca em cada um (cada toque numa página nova),
       anotando o efeito: abriu aba da Kiwi.com com URL válida? mudou a tela? rolou?
       Controle sem efeito = FALHA. Também abre cada promoção e toca nos botões de dentro,
       toca em cada dia do calendário e no botão de compra que aparece.
   (b) 6 rotas (MIA→SAO, NYC→BHZ, LIS→SAO, ORL→RIO, LON→GYN, BHZ→MIA), um mês inteiro de cada:
       toca em TODOS os dias clicáveis e confere o botão de compra: kiwi.com/deep, from/to certos,
       data exata do dia, lang=br, moeda certa da rota (usd/eur/gbp), adults=1, aviso e símbolo da moeda.
   (c) zero erros de console vindos do site.
   (d) nenhum texto "WhatsApp"/"Telegram" e nenhum "aviasales" (texto visível ou href).
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

// Aeroportos aceitos para cada código de cidade (o link pode usar a cidade ou um aeroporto dela)
const AEROPORTOS = {
  SAO: ['GRU', 'VCP', 'CGH'], RIO: ['GIG', 'SDU'], BHZ: ['CNF'], NYC: ['JFK', 'EWR', 'LGA'], LON: ['LHR', 'LGW', 'STN', 'LTN', 'LCY'],
  ORL: ['MCO', 'SFB'], MIA: ['MIA', 'FLL'], PAR: ['CDG', 'ORY'], MIL: ['MXP', 'LIN', 'BGY'], ROM: ['FCO', 'CIA']
};
const EUA = ['MIA', 'ORL', 'NYC', 'BOS', 'ATL'];
const BRASIL = ['SAO', 'RIO', 'BHZ', 'GYN', 'SSA', 'REC', 'FOR', 'BSB'];
function moedaEsperada(o, d) {
  const fora = BRASIL.includes(o) ? d : o;
  return EUA.includes(fora) ? 'usd' : (fora === 'LON' ? 'gbp' : 'eur');
}
const SIMBOLO = { usd: 'US$', eur: '€', gbp: '£' };
const NOME_MOEDA = { usd: 'dólar', eur: 'euro', gbp: 'libra' };

const resultados = [];   // { nome, ok, efeito }
const errosConsole = [];
function registrar(nome, ok, efeito) {
  resultados.push({ nome, ok, efeito });
  console.log((ok ? 'PASSOU ' : 'FALHOU ') + nome + ' -> ' + efeito);
}
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

// Desembrulha o link da Travelpayouts (tp.media/r?...&u=) se houver, e devolve o deep link da Kiwi
function deepLinkKiwi(u) {
  try {
    let url = new URL(u);
    if (url.hostname === 'tp.media') url = new URL(url.searchParams.get('u') || '');
    return url.hostname === 'www.kiwi.com' && url.pathname === '/deep' ? url : null;
  } catch (e) { return null; }
}
function urlCompraValida(u) {
  const k = deepLinkKiwi(u);
  return !!k && k.searchParams.get('lang') === 'br' && k.searchParams.get('adults') === '1'
    && k.searchParams.get('return') === 'no-return' && /^\d{2}-\d{2}-\d{4}$/.test(k.searchParams.get('departure') || '')
    && ['usd', 'eur', 'gbp'].includes(k.searchParams.get('currency'));
}
// Confere o link da compra para a rota o→d e a data AAAA-MM-DD. Devolve '' se está certo, ou o motivo.
function conferirLink(u, o, d, data) {
  const k = deepLinkKiwi(u);
  if (!k) return 'não é kiwi.com/deep';
  const [a, m, dd] = data.split('-');
  const p = k.searchParams, erros = [];
  const cidadeOk = (cod, cidade) => cod === cidade || (AEROPORTOS[cidade] || []).includes(cod);
  if (!cidadeOk(p.get('from'), o)) erros.push('from=' + p.get('from'));
  if (!cidadeOk(p.get('to'), d)) erros.push('to=' + p.get('to'));
  if (p.get('departure') !== dd + '-' + m + '-' + a) erros.push('departure=' + p.get('departure'));
  if (p.get('return') !== 'no-return') erros.push('return=' + p.get('return'));
  if (p.get('lang') !== 'br') erros.push('lang=' + p.get('lang'));
  if (p.get('currency') !== moedaEsperada(o, d)) erros.push('currency=' + p.get('currency'));
  if (p.get('adults') !== '1') erros.push('adults=' + p.get('adults'));
  return erros.join(', ');
}

async function novaPagina(context) {
  const page = await context.newPage();
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const onde = (m.location() && m.location().url) || '';
    errosConsole.push(m.text() + ' @ ' + onde);
  });
  page.on('pageerror', (e) => {
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
    const u = aba.url() === 'about:blank' ? await aba.waitForURL(/kiwi\.com|tp\.media/, { timeout: 4000 }).then(() => aba.url()).catch(() => aba.url()) : aba.url();
    await aba.close();
    const ok = urlCompraValida(u) && info.alvo === '_blank' && /noopener/.test(info.rel)
      && (!opts.esperaUrl || opts.esperaUrl(u));
    registrar(rotulo, ok, 'abriu aba nova: ' + u.slice(0, 110) + (ok ? '' : ' (URL/target/rel inválidos)'));
    return { aba: u };
  }
  await dormir(900);
  const depois = await page.evaluate(() => ({ y: window.scrollY, url: location.href, mudou: window.__mudou }));
  const efeitos = [];
  if (depois.url !== antes.url) efeitos.push('mudou o endereço para ' + depois.url.replace(BASE, '/'));
  if (Math.abs(depois.y - antes.y) > 20) efeitos.push('rolou ' + Math.round(antes.y) + '→' + Math.round(depois.y));
  if (depois.mudou > 0) efeitos.push('mudou a tela (' + depois.mudou + ' mudanças)');
  if (opts.esperaAba) { registrar(rotulo, false, 'devia abrir a Kiwi.com e não abriu'); return null; }
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
    // A página da Kiwi.com não precisa carregar de verdade no teste: só conferimos a URL.
    await context.route(/kiwi\.com|tp\.media/, (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<p>ok</p>' }));
    let linksConferidos = 0;

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
        const o0 = await page.inputValue('#origem'), d0 = await page.inputValue('#destino');
        const btn = page.locator('#escolha-link');
        if (!(await btn.isVisible())) registrar('compra do dia ' + data, false, 'botão de compra não apareceu');
        else await tocarEMedir(context, page, btn, '  compra do dia ' + data, { esperaAba: true, esperaUrl: (u) => !conferirLink(u, o0, d0, data) });
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
        await tocarEMedir(context, page, card.locator(qual), 'promoção ' + k + ' ' + qual, qual === 'a.btn' ? { esperaAba: true } : {});
        await page.close();
      }
    }

    /* ---------- promoções: link, moeda, aviso e data de cada uma ---------- */
    const json = JSON.parse(fs.readFileSync(path.join(RAIZ, 'precos.json'), 'utf8'));
    page = await novaPagina(context);
    const promosNaTela = await page.$$eval('#promos .promo', (cs) => cs.map((c) => ({
      rota: c.querySelector('.promo-rota').innerText.replace(/\s+/g, ' ').trim(),
      valor: c.querySelector('.promo-valor').innerText.replace(/\s+/g, ' ').trim(),
      dia: c.querySelector('.promo-dia').innerText.trim(),
      href: c.querySelector('a.btn').getAttribute('href'),
      aviso: c.querySelector('.aviso-parceiro').textContent.trim()
    })));
    await page.close();
    const valorUsd = (v) => { const n = Number(v.replace(/[^0-9]/g, '')); return v.startsWith('€') ? n * 1.08 : (v.startsWith('£') ? n * 1.27 : n); };
    promosNaTela.forEach((p, k) => {
      const k2 = deepLinkKiwi(p.href);
      const o = k2 && k2.searchParams.get('from'), d = k2 && k2.searchParams.get('to');
      const fonte = (json.promocoes || []).find((x) => x.origem === o && x.destino === d) || {};
      const moeda = o && d ? moedaEsperada(o, d) : '';
      const motivo = fonte.data ? conferirLink(p.href, o, d, fonte.data) : 'promoção não encontrada no precos.json';
      const simboloOk = p.valor.startsWith(SIMBOLO[moeda] + ' ') && /^\S+ [\d.]+$/.test(p.valor);   // ex.: "US$ 389" (sem centavos)
      const avisoOk = p.aviso === 'Você vai para a Kiwi.com, nossa parceira. O site é em português e o preço aparece em ' + NOME_MOEDA[moeda] + '.';
      const ordemOk = k === 0 || valorUsd(promosNaTela[k - 1].valor) <= valorUsd(p.valor);
      if (!motivo) linksConferidos++;
      registrar('promoção ' + k + ' ' + p.rota + ' ' + p.valor + ' (' + p.dia + ')', !motivo && simboloOk && avisoOk && ordemOk,
        [motivo || 'link ok', simboloOk ? 'moeda ok' : 'moeda errada', avisoOk ? 'aviso ok' : 'aviso errado: ' + p.aviso, ordemOk ? 'ordem ok' : 'fora de ordem'].join('; '));
    });
    console.log('EXEMPLOS DE PROMOÇÕES: ' + promosNaTela.slice(0, 3).map((p) => p.rota + ' ' + p.valor + ' em ' + p.dia).join(' | '));

    /* ---------- (b) 6 rotas, um mês inteiro: TODOS os dias clicáveis ---------- */
    const ROTAS_TESTE = [['MIA', 'SAO'], ['NYC', 'BHZ'], ['LIS', 'SAO'], ['ORL', 'RIO'], ['LON', 'GYN'], ['BHZ', 'MIA']];
    const mesTeste = json.meses[1] || json.meses[0];   // mês que vem: todos os dias clicáveis
    for (const [o, d] of ROTAS_TESTE) {
      const moeda = moedaEsperada(o, d);
      page = await novaPagina(context);
      await page.selectOption('#origem', o);
      await page.dispatchEvent('#origem', 'change');
      await page.selectOption('#destino', d);
      await page.selectOption('#mes', mesTeste);
      await page.locator('#btn-buscar').tap();
      await dormir(800);
      const nome = o + '→' + d + ' ' + mesTeste;
      // Cartão principal (só existe quando há preço)
      if (await page.locator('#com-dados').isVisible()) {
        const href = await page.getAttribute('#melhor-link', 'href');
        const valor = (await page.innerText('#melhor-valor')).trim();
        const quando = await page.$eval('#calendario .dia.campeao', (b) => b.dataset.data).catch(() => null);
        const motivo = quando ? conferirLink(href, o, d, quando) : 'sem dia campeão';
        if (!motivo) linksConferidos++;
        registrar(nome + ' cartão principal ' + valor, !motivo && valor.startsWith(SIMBOLO[moeda] + '\u00a0'), motivo || href.slice(0, 120));
      } else console.log(nome + ': sem preço guardado (só calendário "ver")');
      const moedaCal = (await page.innerText('#cal-moeda')).trim();
      registrar(nome + ' moeda do calendário', moedaCal === SIMBOLO[moeda], moedaCal);
      const dias = page.locator('#calendario .dia:not(.passado):not(.vazio)');
      const n = await dias.count();
      let certos = 0, comPreco = 0; const erros = [];
      for (let i = 0; i < n; i++) {
        const dia = dias.nth(i);
        const data = await dia.getAttribute('data-data');
        const sem = await dia.evaluate((b) => b.classList.contains('sem'));
        if (!sem) comPreco++;
        await dia.tap();
        await dormir(60);
        const btn = page.locator('#escolha-link');
        if (!(await btn.isVisible())) { erros.push(data + ': botão não apareceu'); continue; }
        const href = await btn.getAttribute('href');
        const texto = (await btn.innerText()).trim();
        const cartao = (await page.locator('#escolha').innerText()).replace(/\s+/g, ' ');
        const motivo = conferirLink(href, o, d, data);
        const textoOk = sem ? (texto === 'Ver voos deste dia' && /Preço ao vivo na Kiwi\.com/.test(cartao))
          : (texto === 'Comprar este dia' && new RegExp('— ' + SIMBOLO[moeda].replace('$', '\\$') + ' [\\d.]+ ').test(cartao));
        const avisoOk = cartao.includes('Você vai para a Kiwi.com, nossa parceira. O site é em português e o preço aparece em ' + NOME_MOEDA[moeda] + '.');
        if (!motivo && textoOk && avisoOk) { certos++; linksConferidos++; } else erros.push(data + ': ' + (motivo || (!textoOk ? 'texto "' + texto + '"' : 'aviso errado')));
      }
      registrar(nome + ': ' + n + ' dias clicáveis (' + comPreco + ' com preço)', n > 0 && certos === n, certos + '/' + n + ' certos' + (erros.length ? ' — ' + erros.slice(0, 3).join(' | ') : ''));
      // Abre de verdade o botão do primeiro e do último dia
      for (const idx of [0, n - 1]) {
        const dia = dias.nth(idx); const data = await dia.getAttribute('data-data');
        await dia.tap(); await dormir(200);
        await tocarEMedir(context, page, page.locator('#escolha-link'), '  ' + nome + ' abrir ' + data, { esperaAba: true, esperaUrl: (u) => !conferirLink(u, o, d, data) });
      }
      if (o === 'MIA') await page.screenshot({ path: path.join(RAIZ, 'shot-mobile.png'), fullPage: true });
      await page.close();
    }

    /* ---------- rota sem nenhum preço: sugestões + calendário continuam úteis ---------- */
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

    /* ---------- (d) sem WhatsApp/Telegram, sem aviasales; links seguros ---------- */
    page = await novaPagina(context);
    const html = await page.evaluate(() => document.documentElement.outerHTML);
    const texto = await page.evaluate(() => document.body.innerText);
    const proibido = /whats\s*app|telegram/i.test(html) || /whats\s*app|telegram/i.test(texto);
    registrar('sem "WhatsApp"/"Telegram" na página', !proibido, proibido ? 'ainda aparece' : 'nenhuma ocorrência');
    // Abre todas as promoções e detalhes para o texto escondido também contar
    await page.$$eval('details', (ds) => ds.forEach((x) => { x.open = true; }));
    const textoTudo = await page.evaluate(() => document.body.innerText);
    const hrefs = await page.$$eval('[href], [src], [action]', (els) => els.map((e) => e.getAttribute('href') || e.getAttribute('src') || e.getAttribute('action')));
    const comAvia = /aviasales/i.test(textoTudo) || hrefs.some((h) => /aviasales/i.test(h || ''));
    const fonteHtml = fs.readFileSync(path.join(RAIZ, 'index.html'), 'utf8');
    registrar('nenhum "aviasales" visível, em href ou no index.html', !comAvia && !/aviasales/i.test(fonteHtml), comAvia ? 'ainda aparece na página' : (/aviasales/i.test(fonteHtml) ? 'ainda está no index.html' : 'nenhuma ocorrência'));
    const linksRuins = await page.$$eval('a', (as) => as.filter((a) => {
      const h = a.getAttribute('href') || '';
      if (!h || h === '#') return true;
      if (/^http:\/\//.test(h)) return true;
      if (/kiwi\.com|tp\.media/.test(h) && (a.target !== '_blank' || !/noopener/.test(a.rel))) return true;
      return false;
    }).map((a) => a.outerHTML.slice(0, 120)));
    registrar('links: nenhum href vazio/"#"/http:// e compra com target=_blank rel=noopener', !linksRuins.length, linksRuins.length ? linksRuins.join(' | ') : 'ok');
    const avisos = await page.locator('.embarque .aviso-parceiro').count();
    const textoAviso = avisos ? (await page.locator('.embarque .aviso-parceiro').textContent()).trim() : '';
    registrar('aviso da Kiwi.com antes do botão principal', avisos === 1 && /^Você vai para a Kiwi\.com, nossa parceira\. O site é em português e o preço aparece em (dólar|euro|libra)\.$/.test(textoAviso), textoAviso);
    await page.close();

    const desk = await browser.newContext({ viewport: { width: 1366, height: 900 }, locale: 'pt-BR', timezoneId: 'America/Sao_Paulo' });
    const pd = await novaPagina(desk);
    await pd.screenshot({ path: path.join(RAIZ, 'shot-desktop.png'), fullPage: true });
    await desk.close();

    /* ---------- (c) erros de console ---------- */
    registrar('zero erros de console do site', errosConsole.length === 0, errosConsole.length ? errosConsole.slice(0, 5).join(' | ') : 'nenhum');

    console.log('LINKS DE COMPRA CONFERIDOS (rota, data, lang, moeda, adultos): ' + linksConferidos);
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
