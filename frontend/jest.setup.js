import '@testing-library/jest-dom';
/* eslint-disable @typescript-eslint/no-require-imports */

const React = require('react');

function flushMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

if (typeof React.act !== 'function') {
  React.act = async (callback) => {
    if (typeof callback !== 'function') {
      throw new Error('act() requires a callback');
    }
    
    let result;
    let error;
    
    try {
      result = callback();
    } catch (e) {
      error = e;
    }
    
    await flushMicrotasks();
    
    if (error) {
      throw error;
    }
    
    if (result && typeof result.then === 'function') {
      return result;
    }
    
    return result;
  };
}

global.React = React;
