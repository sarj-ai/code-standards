export interface DomainView { id: string }
export interface ReadPort { read(): DomainView }
export interface AsyncReadPort { read(): Promise<DomainView | null> }
export interface ReadPropertyPort { read: () => DomainView }
export interface GenericReadPort<T> { read(): T }
export abstract class ReadBase { abstract read(): DomainView }
export interface ReadCallable { (): DomainView }
export interface ViewPort { readonly view: DomainView }
export abstract class ViewBase { abstract get view(): DomainView }
export interface AdapterPort { readonly read: ReadCallable }
