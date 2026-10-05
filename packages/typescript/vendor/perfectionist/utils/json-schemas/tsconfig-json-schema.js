let tsconfigJsonSchema = {
  properties: {
    rootDir: {
      description: 'Specifies the tsConfig root directory.',
      type: 'string',
    },
    filename: {
      description: 'Specifies the tsConfig filename.',
      type: 'string',
    },
  },
  additionalProperties: false,
  required: ['rootDir'],
  type: 'object',
}
export { tsconfigJsonSchema }
