// 共用的 SSE 對話串流處理邏輯，從 chatStore.js 抽出，供 chatStore.js 與 externalChatStore.js 共用，
// 避免同一段容易出錯的 fetch + SSE 解析邏輯維護兩份。
export async function streamChat({ endpoint, headers, payload, messages, assistantMessageId, setLoading }) {
  setLoading(true)

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let rawContentAccumulator = ''
    let reasoningAccumulator = ''

    let currentEvent = null

    while (true) {
      const { value, done } = await reader.read()
      if (value) {
        buffer += decoder.decode(value, { stream: true })
      }

      const lines = buffer.split('\n')
      if (!done) {
        buffer = lines.pop()
      } else {
        buffer = ''
      }

      for (const line of lines) {
        const trimmedLine = line.trim()
        if (trimmedLine.startsWith('event:')) {
          currentEvent = trimmedLine.replace('event:', '').trim()
        } else if (trimmedLine.startsWith('data:')) {
          const dataStr = trimmedLine.replace('data:', '').trim()
          if (!dataStr) continue

          try {
            const data = JSON.parse(dataStr)
            if (currentEvent === 'chunk') {
              if (data.type === 'reasoning') {
                reasoningAccumulator += data.content
              } else if (data.type === 'content') {
                rawContentAccumulator += data.content
              } else if (data.type === 'done') {
                // Completed
              }

              const msg = messages.find(m => m.id === assistantMessageId)
              if (msg) {
                let contentToShow = rawContentAccumulator
                let thinkingToShow = reasoningAccumulator
                let hasClosedThinkTag = false

                let thinkStartIdx = rawContentAccumulator.indexOf('<think>')
                let tagLength = 7
                let thinkEndIdx = -1
                let endTagLength = 8

                if (thinkStartIdx === -1) {
                  // Try <thought> tag
                  thinkStartIdx = rawContentAccumulator.indexOf('<thought>')
                  if (thinkStartIdx !== -1) {
                    tagLength = 9
                    thinkEndIdx = rawContentAccumulator.indexOf('</thought>')
                    endTagLength = 10
                  }
                } else {
                  thinkEndIdx = rawContentAccumulator.indexOf('</think>')
                }

                if (thinkStartIdx !== -1) {
                  if (thinkEndIdx !== -1) {
                    hasClosedThinkTag = true
                    thinkingToShow = reasoningAccumulator + rawContentAccumulator.substring(thinkStartIdx + tagLength, thinkEndIdx)
                    contentToShow = rawContentAccumulator.substring(0, thinkStartIdx) + rawContentAccumulator.substring(thinkEndIdx + endTagLength)
                  } else {
                    thinkingToShow = reasoningAccumulator + rawContentAccumulator.substring(thinkStartIdx + tagLength)
                    contentToShow = rawContentAccumulator.substring(0, thinkStartIdx)
                  }
                }

                msg.thinking = thinkingToShow.trim()
                msg.content = contentToShow
                msg.isThinking = (reasoningAccumulator.length > 0 && contentToShow.length === 0) || (thinkStartIdx !== -1 && !hasClosedThinkTag)

                // Update steps dynamically
                if (msg.steps) {
                  if (data.type === 'reasoning' || msg.isThinking) {
                    const thinkStep = msg.steps.find(s => s.key === 'llm_thinking')
                    if (thinkStep) {
                      thinkStep.status = 'running'
                      thinkStep.content = msg.thinking || reasoningAccumulator
                    }
                  }
                  if (data.type === 'content' && contentToShow.length > 0) {
                    const thinkStep = msg.steps.find(s => s.key === 'llm_thinking')
                    if (thinkStep && thinkStep.status === 'running') {
                      thinkStep.status = 'success'
                    }
                    const conclStep = msg.steps.find(s => s.key === 'conclusion')
                    if (conclStep) {
                      conclStep.status = 'running'
                      conclStep.content = contentToShow
                    }
                  }
                }
              }
            } else if (currentEvent === 'step') {
              const msg = messages.find(m => m.id === assistantMessageId)
              if (msg) {
                if (data.step === 'profile_candidates') {
                  msg.dbQueryCandidates = data.candidates || []
                  msg.awaitingProfileSelection = true
                } else if (msg.steps) {
                  let stepObj = msg.steps.find(s => s.key === data.step)
                  if (!stepObj) {
                    stepObj = { key: data.step, name: data.label || data.step, status: 'pending', content: '', expanded: false }
                    const insertAt = msg.steps.findIndex(s => s.key === 'llm_thinking')
                    msg.steps.splice(insertAt === -1 ? msg.steps.length : insertAt, 0, stepObj)
                  }
                  stepObj.status = data.status
                  stepObj.content = data.content
                  if (data.label) {
                    stepObj.name = data.label
                  }
                }
              }
            } else if (currentEvent === 'message') {
              const msg = messages.find(m => m.id === assistantMessageId)
              if (msg && typeof data.delta === 'string') {
                msg.content = data.delta
                const conclStep = msg.steps?.find(s => s.key === 'conclusion')
                if (conclStep) {
                  conclStep.status = 'success'
                  conclStep.content = data.delta
                }
              }
            } else if (currentEvent === 'sources') {
              const msg = messages.find(m => m.id === assistantMessageId)
              if (msg) {
                msg.sources = data.sources
                msg.contextSummary = data.context_summary || null
                msg.attachments = data.attachments || null
              }
            }
          } catch (e) {
            console.error('Failed to parse SSE JSON data:', dataStr, e)
          }
        }
      }

      if (done) break
    }
  } catch (error) {
    console.error('Error during streaming:', error)
    const msg = messages.find(m => m.id === assistantMessageId)
    if (msg) {
      msg.content = `[連線錯誤] 無法取得回覆：${error.message}`
      if (msg.steps) {
        const conclStep = msg.steps.find(s => s.key === 'conclusion')
        if (conclStep) {
          conclStep.status = 'failed'
          conclStep.content = `[連線錯誤] ${error.message}`
        }
      }
    }
  } finally {
    setLoading(false)
    const msg = messages.find(m => m.id === assistantMessageId)
    if (msg) {
      msg.isThinking = false
      if (msg.steps && !msg.awaitingProfileSelection) {
        msg.steps.forEach(s => {
          if (s.status === 'running' || s.status === 'pending') {
            s.status = 'success'
            if (s.key === 'conclusion') {
              s.content = msg.content
            }
          }
        })
      }
    }
  }
}
