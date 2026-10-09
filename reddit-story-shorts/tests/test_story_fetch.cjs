const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
    let startup;
    const elements = Object.fromEntries([
        'fetch-posts-btn', 'sub-select', 'sort-select', 'limit-select',
        'posts-container', 'reddit-source-status',
    ].map(id => [id, {
        disabled: false, value: '', children: [], innerHTML: '',
        addEventListener(type, callback) { this[type] = callback; },
        appendChild(child) { this.children.push(child); },
    }]));
    elements['sub-select'].value = 'AmItheAsshole';
    elements['sort-select'].value = 'hot';
    elements['limit-select'].value = '25';
    let requestUrl;
    const context = vm.createContext({
        document: {
            addEventListener(type, callback) { startup = callback; },
            getElementById(id) { return elements[id]; },
            createElement() { return {}; },
        },
        console, setTimeout, clearTimeout, AbortController,
        fetch: async url => {
            requestUrl = url;
            return { ok: true, json: async () => ({ success: true, source: 'reddit_rss',
                posts: [{ title: 'Fetched story', body: 'Story body', author: 'author', subreddit: 'r/AmItheAsshole' }],
            }) };
        },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), context);
    await context.fetchPosts();
    assert.match(requestUrl, /subreddit=AmItheAsshole/);
    assert.equal(elements['posts-container'].children.length, 1);
    assert.match(elements['posts-container'].children[0].innerHTML, /Fetched story/);
    assert.equal(elements['fetch-posts-btn'].disabled, false);

    context.fetch = async () => { const error = new Error(); error.name = 'AbortError'; throw error; };
    await context.fetchPosts();
    assert.match(elements['posts-container'].innerHTML, /request timed out/);
    assert.equal(elements['fetch-posts-btn'].disabled, false);

    for (const name of ['loadGameplayList', 'loadMusicList', 'loadGallery', 'loadNarratorVoices', 'loadSubreddits']) {
        context[name] = async () => {};
    }
    context.fetchPosts = async () => {};
    startup();
    assert.equal(elements['fetch-posts-btn'].click, context.fetchPosts);
    console.log('Story fetch rendering, error recovery, and button binding passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
